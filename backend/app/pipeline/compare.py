"""交叉比对引擎：第 2 层。

把同一个字段在不同文件里的值放到一起比，得出 6 种结论之一：

  MATCH           有值的文件都一致
  CONFLICT        有值且不一致
  MISSING_IN_SOME 有的有值，有的该有没抽到
  NOT_CHECKED     没规则覆盖或信息不足（必须给 note 说明原因）
  UNRECOGNIZED    相关文件里都没识别出来
  SINGLE_SOURCE   只有一份文件有该字段

**canonical_value 永远是 null。系统不判断哪份文件正确，只定位矛盾。**

两个容易被低估的漏报点，这里做了专门处理：

1. 金额只看数字 —— `100 USD` 与 `100 EUR` 会被判成 MATCH。数字相同不代表
   金额相同，币种不同就是矛盾，所以金额比对同时比较「数值 + 币种」。
   再退一步：**只要有一份文件的币种没识别出来，即使数字相同也不能判 MATCH**
   （不知道是不是同一种货币），此时给 `NOT_CHECKED` + note，如实说明「无法确认」。
2. 描述只看整体相似度 —— 长描述里只差一个颜色/材质词，词集相似度仍然很高
   （如两个 9 词的描述差 1 个颜色词，Jaccard 仍达 0.89），差异会被掩盖。
   所以描述比对额外加一道「关键属性闸门」：颜色/材质词或带数字的规格/型号
   一旦出现在差异词集里，无论整体相似度多高都判 CONFLICT。
"""

from __future__ import annotations

from typing import Callable

from ..schema_fields import (
    BY_KEY,
    CORE_COMPARABLE,
    IDENTIFIERS,
    ITEM_LEVEL,
    RULE_REQUIRED_FIELDS,
)

# 核心字段之外，标识类字段只在「至少两份文件都涉及」时才出比对行，避免噪音
_IDENTIFIER_KEYS = {s.key for s in IDENTIFIERS if s.key != "document_no"}
CORE_KEYS = [s.key for s in CORE_COMPARABLE]
# 品名行级字段的比对顺序
ITEM_KEYS = [s.key for s in ITEM_LEVEL]

# 描述类字段用词集相似度判等：不同写法归一后可能不完全一致
_STRING_SIMILARITY_KEYS = {"description"}
_SIMILARITY_THRESHOLD = 0.7

# 关键属性词：颜色 / 材质。只要两份描述在这类词上有出入，就判为不一致 ——
# 这类差异决定的是「是不是同一件货」，绝不能被相似度掩盖。
# 中英文都收：归一后常见词会变中文，词表没覆盖的仍保持英文。
_CRITICAL_TOKENS = {
    # 颜色
    "白", "黑", "蓝", "红", "绿", "黄", "灰", "棕", "粉", "紫", "橙", "银", "金", "米",
    "WHITE", "BLACK", "BLUE", "RED", "GREEN", "YELLOW", "GREY", "GRAY", "BROWN",
    "PINK", "PURPLE", "ORANGE", "SILVER", "GOLD", "BEIGE", "IVORY", "CREAM",
    # 材质
    "陶瓷", "玻璃", "塑料", "不锈钢", "铝", "铁", "竹", "木质", "纸", "棉",
    "CERAMIC", "PORCELAIN", "GLASS", "PLASTIC", "STEEL", "ALUMINUM", "IRON",
    "WOOD", "WOODEN", "BAMBOO", "COTTON", "PAPER",
}

_USABLE = {"EXTRACTED", "LOW_CONFIDENCE"}
_LACKING = {"MISSING_IN_DOC", "UNRECOGNIZED", "NORMALIZE_FAILED"}


def _canonical(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 6)
    return str(value).strip().upper() if value is not None else None


def _tokens(value) -> set[str]:
    if value is None:
        return set()
    return {t for t in str(value).split() if t}


def _similarity(a, b) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _has_digit(token: str) -> bool:
    return any(ch.isdigit() for ch in token)


def _agree_description(values: list) -> tuple[bool, bool, str | None]:
    """描述比对：相似度阈值 + 关键属性闸门。返回 (是否一致, 是否模糊一致, 原因)。"""
    canon = [str(v) for v in values]
    if len(set(canon)) == 1:
        return True, False, None

    sets = [_tokens(v) for v in canon]
    worst = 1.0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i], sets[j]
            if not a or not b:
                worst = 0.0
                continue
            worst = min(worst, len(a & b) / len(a | b))
            diff = a ^ b
            if diff & _CRITICAL_TOKENS:
                hit = "、".join(sorted(diff & _CRITICAL_TOKENS))
                return False, False, f"货物描述在关键属性（{hit}）上存在差异，不能判为一致。"
            if any(_has_digit(t) for t in diff):
                return False, False, "货物描述在规格/型号/容量上存在差异，不能判为一致。"
    agreed = worst >= _SIMILARITY_THRESHOLD
    return agreed, agreed, None


def _agree(field_key: str, values: list) -> tuple[bool, bool, str | None]:
    """返回 (是否一致, 是否属于「归一后一致但原文写法不同」, 不一致原因)。"""
    if len(values) < 2:
        return True, False, None
    if field_key in _STRING_SIMILARITY_KEYS:
        return _agree_description(values)
    canon = [_canonical(v) for v in values]
    if field_key == "hs_code":
        # 同一个编码在不同单证上可能写到 6 位 / 8 位 / 10 位。
        # 互为前缀即视为一致，否则会把「写法详略不同」误报成冲突。
        strs = [str(v) for v in canon if v is not None]
        if len(strs) >= 2:
            longest = max(strs, key=len)
            if len(min(strs, key=len)) >= 6 and all(longest.startswith(s) for s in strs):
                return True, len(set(strs)) > 1, None
    return len(set(canon)) == 1, False, None


def _currency_of(field: dict) -> str | None:
    """金额字段的单位即币种（extract.py 在抽取时写入 unit）。"""
    unit = field.get("unit")
    return unit.upper() if isinstance(unit, str) and unit else None


def _agree_money(usable: list[tuple[dict, dict]]) -> tuple[str, str | None]:
    """金额比对：数值与币种必须同时一致。

    返回 (结论, 原因)，结论 ∈ {"MATCH", "CONFLICT", "UNVERIFIABLE"}。

    「UNVERIFIABLE」是必须单独列出的一档：只要有一份文件的币种没识别出来，
    即使数字完全相同也不能判 MATCH —— 不知道是不是同一种货币，就无法确认
    金额是否一致。这类「信息不足」要显式说出来，不能让用户以为检查过了。
    """
    numbers = {_canonical(f.get("normalized_value")) for _, f in usable}
    currencies = sorted({c for c in (_currency_of(f) for _, f in usable) if c})
    known = sum(1 for _, f in usable if _currency_of(f))

    if len(currencies) > 1:
        joined = " / ".join(currencies)
        if len(numbers) == 1:
            return "CONFLICT", f"金额数值一致，但币种不同（{joined}），不能判为一致。"
        return "CONFLICT", f"金额数值与币种均不一致（币种 {joined}）。"

    if len(numbers) != 1:
        return "CONFLICT", None

    # 数值一致 —— 还要确认每份文件的币种都识别到了，否则无法确认
    if known < len(usable):
        unknown = len(usable) - known
        return "UNVERIFIABLE", (
            f"金额数值一致，但有 {unknown} 份文件未识别出币种，"
            "无法确认金额是否一致，请人工核对。"
        )
    return "MATCH", None


def _severity_for_conflict(value_type: str) -> str:
    # 数字与金额对不上，通常会直接卡住报关；文本差异多为写法问题
    return "ERROR" if value_type in ("NUMBER", "MONEY") else "WARNING"


def build_comparisons(
    documents: list[dict],
    extractions: list[dict],
    hs_covered: Callable[[str | None, str | None], bool],
    destination_country: str | None = None,
    destination_country_name: str | None = None,
) -> list[dict]:
    """documents / extractions 都是契约形状的字典。"""
    ok_docs = [d for d in documents if d["process_status"] == "EXTRACTED"]
    failed_docs = [d for d in documents if d["process_status"] in ("FAILED", "UNSUPPORTED")]

    by_file: dict[str, dict] = {e["file_id"]: e for e in extractions}

    def rule_uncovered(key: str, usable_rows: list[tuple[dict, dict]]) -> bool:
        """字段是否「必须过规则校验」但确实没有规则覆盖它。"""
        if key not in RULE_REQUIRED_FIELDS:
            return False
        code = usable_rows[0][1].get("normalized_value") if usable_rows else None
        return not hs_covered(destination_country, code)

    # 已失败的文件不进入 values（否则会污染 MATCH / SINGLE_SOURCE 的判定），
    # 改用 note 与 errors[] 说明它没被纳入
    failed_note = ""
    if failed_docs:
        names = "、".join(d["file_name"] for d in failed_docs)
        failed_note = f"{names} 未能处理，本次比对未包含该文件数据。"

    # 收集：field_key -> [(document, field)]
    collected: dict[str, list[tuple[dict, dict]]] = {}
    for doc in ok_docs:
        ext = by_file.get(doc["file_id"])
        if not ext:
            continue
        for f in ext["fields"]:
            if f["field_key"] == "document_no":
                continue
            collected.setdefault(f["field_key"], []).append((doc, f))

    comparisons: list[dict] = []
    index = 0

    ordered_keys = CORE_KEYS + sorted(k for k in collected if k not in CORE_KEYS)

    for key in ordered_keys:
        rows = collected.get(key, [])
        applicable = [(d, f) for d, f in rows if f["status"] != "NOT_IN_DOC"]
        if not applicable:
            # 所有文件都「本就不适用」=> 不生成比对行，不占用问题清单
            continue
        if key in _IDENTIFIER_KEYS and len(applicable) < 2:
            # 标识类字段只有一份文件涉及，比对没有意义
            continue

        usable = [(d, f) for d, f in applicable if f["status"] in _USABLE]
        lacking = [(d, f) for d, f in applicable if f["status"] in _LACKING]

        spec = BY_KEY[key]
        value_type = spec.value_type
        unit = spec.unit
        if key == 'packages':
            package_units = {field.get('unit') for _, field in usable}
            unit = next(iter(package_units)) if len(package_units) == 1 else None
        values_out = [_comparison_value(d, f) for d, f in applicable]

        status = "SINGLE_SOURCE"
        severity = "INFO"
        rule_id: str | None = None
        note: str | None = None

        if len(usable) >= 2:
            money_verdict: str | None = None
            if key == "total_amount":
                money_verdict, reason = _agree_money(usable)
                agreed, fuzzy = money_verdict == "MATCH", False
            else:
                agreed, fuzzy, reason = _agree(key, [f["normalized_value"] for _, f in usable])

            if money_verdict == "UNVERIFIABLE":
                # 币种没识别全 => 信息不足，显式标为「未校验」。判 MATCH 会让用户
                # 以为金额对得上，而实际上连是不是同一种货币都不知道。
                status = "NOT_CHECKED"
                severity = "WARNING"
                note = reason
            elif not agreed:
                status = "CONFLICT"
                severity = _severity_for_conflict(value_type)
                rule_id = "CROSS_CHECK_001"
                note = reason or (_lacking_note(lacking) if lacking else None)
            elif rule_uncovered(key, usable):
                status = "NOT_CHECKED"
                severity = "WARNING"
                note = _not_checked_note(destination_country_name)
            elif lacking:
                status = "MISSING_IN_SOME"
                severity = "WARNING"
                rule_id = "CROSS_CHECK_001"
                note = _lacking_note(lacking)
            else:
                status = "MATCH"
                severity = "INFO"
                rule_id = "CROSS_CHECK_001"
                if fuzzy:
                    note = "归一后一致，但原始写法不同。"
        elif len(usable) == 1:
            if rule_uncovered(key, usable):
                status = "NOT_CHECKED"
                severity = "WARNING"
                note = _not_checked_note(destination_country_name)
            elif lacking:
                status = "MISSING_IN_SOME"
                severity = "WARNING"
                rule_id = "CROSS_CHECK_001"
                note = _lacking_note(lacking)
            else:
                status = "SINGLE_SOURCE"
                severity = "INFO"
                note = f"只有 {usable[0][0]['file_name']} 提供该字段，无法交叉比对。"
        else:
            # 一个可用值都没有
            status = "UNRECOGNIZED"
            severity = "WARNING"
            note = _lacking_note(lacking)

        if failed_note:
            note = f"{note} {failed_note}".strip() if note else failed_note
        if key == 'packages' and status == 'MATCH' and unit is None:
            status, severity, rule_id = 'NOT_CHECKED', 'WARNING', None
            note = '包装类型或单位未明确，不能确认跨文件一致；保留件数，待核对原件。'

        # 金额的单位是币种；多份文件币种不同时，无法用单一单位表述，留 null
        if key == "total_amount":
            currencies = sorted({c for c in (_currency_of(f) for _, f in usable) if c})
            unit = currencies[0] if len(currencies) == 1 else None

        index += 1
        comparisons.append(
            {
                "comparison_id": f"cmp_{index}",
                "field_key": key,
                "label": spec.label,
                "value_type": value_type,
                "unit": unit,
                "status": status,
                "canonical_value": None,  # 恒为 null
                "severity": severity,
                "rule_id": rule_id,
                "note": note,
                "values": values_out,
            }
        )

    return comparisons


def _comparison_value(doc: dict, field: dict) -> dict:
    return {
        "file_id": doc["file_id"],
        "file_name": doc["file_name"],
        "raw_value": field.get("raw_value"),
        "normalized_value": field.get("normalized_value"),
        "field_status": field["status"],
        "page": field.get("page"),
        "bbox": field.get("bbox"),
    }


def _lacking_note(lacking: list[tuple[dict, dict]]) -> str:
    parts = []
    for doc, field in lacking:
        reason = {
            "MISSING_IN_DOC": "按规则应有但文件中未找到",
            "UNRECOGNIZED": "定位到了但读不出值",
            "NORMALIZE_FAILED": "读出值但无法归一",
        }.get(field["status"], "未能取值")
        parts.append(f"{doc['file_name']}（{reason}）")
    return "；".join(parts) + "，无法完成比对。"


def _not_checked_note(country_name: str | None) -> str:
    where = country_name or "该目的国"
    return f"当前未配置{where}对应该字段的校验规则，该项未经校验，请人工确认。"


# ==========================================================================
# 品名级比对（v0.2）：同一条 items[] 行组内，各文件对应行互比
# ==========================================================================
def build_item_comparisons(
    items: list[dict],
    documents: list[dict],
    extractions: list[dict],
    hs_covered: Callable[[str | None, str | None], bool],
    destination_country: str | None = None,
    destination_country_name: str | None = None,
    start_index: int = 0,
    unchecked_descriptions: set[tuple[str, int]] | None = None,
) -> list[dict]:
    """按行组逐组比对，产出 scope=ITEM 的比对条目。

    与票级的唯一区别是「值从哪来」：票级取 `extractions[].fields[]`，
    品名级取 `extractions[].line_items[<member.item_no>].fields[]`。

    **对齐不成立时不下结论**：行组状态为 UNALIGNED 时，一律给 NOT_CHECKED。
    我们不知道哪一行对应哪一行，任何 MATCH / CONFLICT 都是编出来的。
    """
    if not items:
        return []

    doc_by_id = {d["file_id"]: d for d in documents}
    failed_docs = [d for d in documents if d["process_status"] in ("FAILED", "UNSUPPORTED")]
    failed_note = ""
    if failed_docs:
        names = "、".join(d["file_name"] for d in failed_docs)
        failed_note = f"{names} 未能处理，本行组的比对未包含该文件数据。"

    rows_by_file: dict[str, dict[int, dict]] = {}
    for ext in extractions:
        rows_by_file[ext["file_id"]] = {
            li["item_no"]: li for li in (ext.get("line_items") or [])
        }

    comparisons: list[dict] = []
    index = start_index

    for item in items:
        item_id = item["item_id"]
        aligned = item["alignment_status"]
        members = item["members"]

        collected: dict[str, list[tuple[dict, dict]]] = {}
        rows_seen = 0
        for m in members:
            doc = doc_by_id.get(m["file_id"])
            row = rows_by_file.get(m["file_id"], {}).get(m["item_no"])
            if doc is None or row is None:
                continue
            rows_seen += 1
            from ..doc_profile import profile_of
            from .extract import _field
            row_fields = list(row.get("fields", []))
            present = {f['field_key'] for f in row_fields}
            for key in (profile_of(doc.get('doc_type')) or set()) & set(ITEM_KEYS) - present:
                row_fields.append(_field(BY_KEY[key], 'MISSING_IN_DOC', page=None))
            for f in row_fields:
                if f["status"] == "NOT_IN_DOC":
                    continue
                collected.setdefault(f["field_key"], []).append((doc, f))

        if rows_seen == 0:
            continue

        for key in ITEM_KEYS:
            rows = collected.get(key)
            if not rows:
                continue

            usable = [x for x in rows if x[1]["status"] in _USABLE]
            lacking = [x for x in rows if x[1]["status"] in _LACKING]
            spec = BY_KEY.get(key)
            value_type = spec.value_type if spec else "STRING"
            label = spec.label if spec else key
            unit = spec.unit if spec else None
            if key == 'packages':
                package_units = {field.get('unit') for _, field in usable}
                unit = next(iter(package_units)) if len(package_units) == 1 else None
            values_out = [_comparison_value(d, f) for d, f in rows]

            status = "SINGLE_SOURCE"
            severity = "INFO"
            rule_id: str | None = None
            note: str | None = None

            if aligned == "UNALIGNED":
                status = "NOT_CHECKED"
                severity = "WARNING"
                note = "本组各文件的行无法确定一一对应关系，未做比对。" + (
                    item.get("alignment_note") or ""
                )
            elif key == 'description' and any(
                (member['file_id'], member['item_no']) in (unchecked_descriptions or set())
                for member in members
            ):
                status = 'NOT_CHECKED'
                severity = 'WARNING'
                note = '品名未取得同一货号区域的两路 OCR 一致核验；存在文字差异、区域未定位或仅单路恢复布局。保留识别原文与归一值，待人工复核。'
            elif len(usable) < 2 and any(f["status"] == "NORMALIZE_FAILED" for _, f in rows):
                status = "NOT_CHECKED"
                severity = "WARNING"
                note = "至少一份单证的该项无法可靠识别或归一，未做比对；请核对原件。"
            elif len(usable) >= 2:
                money_verdict: str | None = None
                if key in ("amount", "unit_price", "total_amount"):
                    money_verdict, reason = _agree_money(usable)
                    agreed = money_verdict == "MATCH"
                    fuzzy = False
                else:
                    agreed, fuzzy, reason = _agree(key, [f["normalized_value"] for _, f in usable])

                if money_verdict == "UNVERIFIABLE":
                    status = "NOT_CHECKED"
                    severity = "WARNING"
                    note = reason
                elif not agreed:
                    status = "CONFLICT"
                    severity = _severity_for_conflict(value_type)
                    rule_id = "CROSS_CHECK_001"
                    note = reason or (_lacking_note(lacking) if lacking else None)
                elif _rule_uncovered(key, usable, hs_covered, destination_country):
                    status = "NOT_CHECKED"
                    severity = "WARNING"
                    note = _not_checked_note(destination_country_name)
                elif lacking:
                    status = "MISSING_IN_SOME"
                    severity = "WARNING"
                    rule_id = "CROSS_CHECK_001"
                    note = _lacking_note(lacking)
                else:
                    status = "MATCH"
                    severity = "INFO"
                    rule_id = "CROSS_CHECK_001"
                    if fuzzy:
                        note = "归一后一致，但原始写法不同。"
                    if key == "description" and any(
                        f["status"] == "LOW_CONFIDENCE" and f.get("raw_text")
                        for _, f in usable
                    ):
                        severity = "WARNING"
                        note = "OCR 品名经自动校正后与其他单证一致，原识别读数见来源值；请核对原件。"
            elif len(usable) == 1:
                if len(rows) <= 1:
                    # 这一项只有一份文件按行提供（如装箱单本来就没有 HS 列）——
                    # 这不是异常，是分单证类型的正常差异，不能说成「缺失」。
                    only = rows[0][0]["file_name"]
                    status = "SINGLE_SOURCE"
                    severity = "INFO"
                    note = f"只有 {only} 按品名行提供该项，无法交叉比对。"
                else:
                    status = "MISSING_IN_SOME"
                    severity = "WARNING"
                    rule_id = "CROSS_CHECK_001"
                    note = _lacking_note(lacking) if lacking else None
            else:
                status = "UNRECOGNIZED"
                severity = "WARNING"
                note = _lacking_note(lacking) if lacking else "相关文件里都没能识别出该项的值。"

            if failed_note:
                note = f"{note} {failed_note}".strip() if note else failed_note
            if key == 'packages' and status == 'MATCH' and unit is None:
                status, severity, rule_id = 'NOT_CHECKED', 'WARNING', None
                note = '包装类型或单位未明确，不能确认跨文件一致；保留件数，待核对原件。'
            if status in ("SINGLE_SOURCE", "UNALIGNED") and item.get("alignment_note"):
                note = note or item["alignment_note"]

            index += 1
            comparisons.append(
                {
                    "comparison_id": f"cmp_{index}",
                    "scope": "ITEM",
                    "item_id": item_id,
                    "field_key": key,
                    "label": label,
                    "value_type": value_type,
                    "unit": unit,
                    "status": status,
                    "canonical_value": None,
                    "severity": severity,
                    "rule_id": rule_id,
                    "note": note,
                    "values": values_out,
                }
            )

    return comparisons


def _rule_uncovered(
    key: str,
    usable_rows: list[tuple[dict, dict]],
    hs_covered: Callable[[str | None, str | None], bool],
    destination_country: str | None,
) -> bool:
    if key not in RULE_REQUIRED_FIELDS:
        return False
    code = usable_rows[0][1].get("normalized_value") if usable_rows else None
    return not hs_covered(destination_country, code)
