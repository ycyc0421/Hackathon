"""合规规则库：依据目的国规则提示证书缺失与编码归类风险。

规则内容放在 app/rules/countries.json，改规则不用改代码。
每条风险都必须带 rule_id 与 rule_source；给不出规则来源的，rule_id 留 null，
界面会自动显示为「模型建议，未经规则校验」。

两个诚实性要求（这版专门补上）：

1. **规则未核实时必须挑明。** countries.json 里的规则是团队自拟的演示版本，
   来源与适用条件尚未核实。核实前，所有基于规则的提示都要带「未核实」标记，
   并且在任务级 errors[] 里追加一条 WARNING，避免被当成确定的合规结论。
   核实完成后把 countries.json 的 `verified` 改成 true 即可去掉这些标记。

2. **「缺证」不能和「文件解析失败」混为一谈。** 只要本票有文件没解析出来，
   就无法知道那份没解析的文件是不是正好就是缺的那张证书 —— 此时不能断言
   「未提供」，只能提示「有文件未解析，暂无法确认」。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# 规则文件在 app/rules/ 下，本模块位于 app/pipeline/，所以是上两级
RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "countries.json"

# 规则未经核实时的标记
UNVERIFIED_PREFIX = "【演示规则·未经核实】"
UNVERIFIED_DISCLAIMER = "（说明：本提示来自团队自拟的演示规则，来源与适用条件尚未核实，不得作为合规依据。）"
UNVERIFIED_SOURCE_SUFFIX = "（团队自拟的演示规则，来源与适用条件未经核实）"

# 单证类型 -> 中文名（仅用于把提示写得可读）
DOC_TYPE_CN = {
    "COMMERCIAL_INVOICE": "商业发票",
    "PACKING_LIST": "装箱单",
    "BILL_OF_LADING": "提单",
    "CUSTOMS_DECLARATION": "报关单",
    "CERTIFICATE_OF_ORIGIN": "原产地证明",
    "INSURANCE_POLICY": "保险单",
    "OTHER": "其他单证",
}

# 无法解析的文件状态：这些文件的内容我们根本没看到
_UNPARSED_STATUS = {"FAILED", "UNSUPPORTED"}


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def ruleset_verified() -> bool:
    """规则集是否已由 A / C 逐条核实来源与适用条件。

    两道闸门，缺一不可：`verified=true` **且** 填写了 `verified_by`（核实人）。
    只把 verified 改成 true 而不留核实记录，不算数 —— 这样能防止「顺手改个
    布尔值就把『未经核实』标记去掉」，保证标记只在真正核实后才消失。
    """
    data = load_rules()
    if not data.get("verified", False):
        return False
    return bool(str(data.get("verified_by") or "").strip())


def rule_version() -> str:
    return load_rules().get("version", "目的国规则集")


def rule_source_text() -> str:
    """写进 Risk.rule_source：未核实时明确标出。"""
    version = rule_version()
    if ruleset_verified():
        return version
    return f"{version}{UNVERIFIED_SOURCE_SUFFIX}"


def _mark(text: str) -> str:
    """未核实时给标题加前缀（已核实则原样返回）。"""
    return text if ruleset_verified() else f"{UNVERIFIED_PREFIX}{text}"


def _with_disclaimer(text: str) -> str:
    return text if ruleset_verified() else f"{text}{UNVERIFIED_DISCLAIMER}"


def country_rules(code: str | None) -> dict | None:
    if not code:
        return None
    return load_rules()["countries"].get(code.upper())


def match_hs_rule(code: str | None, hs_code: str | None) -> dict | None:
    """按 HS 章号（前两位）匹配归类规则；匹配不到返回 None。"""
    rules = country_rules(code)
    if not rules or not hs_code:
        return None
    hs = str(hs_code)
    best: dict | None = None
    for rule in rules.get("hs_rules", []):
        prefix = str(rule.get("chapter_prefix", ""))
        if prefix and hs.startswith(prefix):
            # 多个前缀命中时取最长的那个（更具体）
            if best is None or len(prefix) > len(str(best.get("chapter_prefix", ""))):
                best = rule
    return best


def hs_covered(code: str | None, hs_code: str | None) -> bool:
    """该编码是否已被目的国规则覆盖。未覆盖 => 比对结论取 NOT_CHECKED。"""
    return match_hs_rule(code, hs_code) is not None


def evaluate_risks(
    task_input: dict,
    documents: list[dict],
    extractions: list[dict],
    items: list[dict] | None = None,
) -> list[dict]:
    """产出风险清单。`items` 是 v0.2 的对齐行组，用于把编码归类风险指到具体品名。"""
    items = items or []
    code = task_input.get("destination_country")
    country_name = task_input.get("destination_country_name") or code or "该目的国"
    rules = country_rules(code)
    doc_types = {d.get("doc_type") for d in documents if d.get("doc_type")}
    doc_count = len(documents)

    # 没解析出来的文件：内容没看到，任何「缺失」结论都要打折扣
    unparsed = [d for d in documents if d.get("process_status") in _UNPARSED_STATUS]

    risks: list[dict] = []
    seq = 0

    def add(**kw) -> None:
        nonlocal seq
        seq += 1
        kw.setdefault("related_item_ids", [])  # 票级风险给空数组
        risks.append({"risk_id": f"rsk_{seq}", "rule_source": rule_source_text(), **kw})

    if rules is None:
        # 目的国没有规则集 —— 如实说明未覆盖，不能假装校验过了
        add(
            type="RULE_UNCOVERED",
            severity="WARNING",
            title=f"目的国 {code or '未知'} 尚未配置合规规则",
            detail=(
                "当前规则集未覆盖该目的国，本票的证书要求与编码归类风险均未经校验，"
                "仅完成了文件间的交叉比对。"
            ),
            related_field_keys=["destination_country"],
            related_file_ids=[],
            destination_country=code,
            rule_id=None,
        )
        return risks

    # 1) 证书类：按规则应当随附、但本票里没识别到的单证
    required_docs = rules.get("required_documents", [])
    missing_reqs = [req for req in required_docs if req["doc_type"] not in doc_types]

    if missing_reqs:
        if unparsed:
            # 有文件没解析 —— 它可能正是缺的那张证书，因此只提示「无法确认」
            unparsed_names = "、".join(d["file_name"] for d in unparsed)
            cert_names = "、".join(
                DOC_TYPE_CN.get(req["doc_type"], req["doc_type"]) for req in missing_reqs
            )
            add(
                type="OTHER",
                severity="WARNING",
                title=_mark(f"有 {len(unparsed)} 份文件未能解析，无法确认是否缺少：{cert_names}"),
                detail=_with_disclaimer(
                    f"本票有 {len(unparsed)} 份文件未能解析（{unparsed_names}）。"
                    f"未解析的文件可能正是所需的 {cert_names}，因此**无法确认**这些单证是否已提供，"
                    "不作「未提供」的结论。请先修复解析（配置多模态兜底或改用带文本层的 PDF），"
                    "或人工核对原件后再判断合规性。"
                ),
                related_field_keys=["destination_country"],
                related_file_ids=[d["file_id"] for d in unparsed],
                destination_country=code,
                rule_id=None,
            )
        else:
            # 全部文件都解析成功，才敢给「未在本票文件中找到」的结论
            for req in missing_reqs:
                add(
                    type="MISSING_CERTIFICATE",
                    severity=req.get("severity", "WARNING"),
                    title=_mark(req["title"].format(country=country_name, doc_count=doc_count)),
                    detail=_with_disclaimer(
                        req["detail"].format(country=country_name, doc_count=doc_count)
                    ),
                    related_field_keys=["hs_code", "destination_country"],
                    related_file_ids=[],
                    destination_country=code,
                    rule_id=req.get("rule_id"),
                )

    # 2) 编码归类：命中的给规则依据，没命中的如实说未经校验
    #    归类风险天然是**按品名**的：马克杯 6911 和水杯 7013 不是同一条风险。
    #    所以行级编码单独判，并且把风险指到具体行组（related_item_ids）。
    item_labels = {i["item_id"]: i["label"] for i in items}
    doc_names = {d["file_id"]: d["file_name"] for d in documents}
    item_of_row: dict[tuple[str, int], str] = {}
    for i in items:
        for m in i["members"]:
            item_of_row[(m["file_id"], m["item_no"])] = i["item_id"]

    def hs_risk(hs: str, file_id: str, item_id: str | None, where: str) -> None:
        rule = match_hs_rule(code, hs)
        suffix = f"（品名：{item_labels.get(item_id, '')}）" if item_id else ""
        related = [item_id] if item_id else []
        if rule:
            add(
                type="HS_CLASSIFICATION",
                severity=rule.get("severity", "WARNING"),
                title=_mark(f"{rule['title']}{suffix}"),
                detail=_with_disclaimer(f"{rule['detail']}（本票编码 {hs}，来自 {where}）"),
                related_field_keys=["hs_code"],
                related_item_ids=related,
                related_file_ids=[file_id],
                destination_country=code,
                rule_id=rule.get("rule_id"),
            )
        else:
            add(
                type="HS_CLASSIFICATION",
                severity="WARNING",
                title=f"HS 编码 {hs} 未经规则校验{suffix}",
                detail=(
                    f"该编码来自 {where}，当前规则集未覆盖{country_name}"
                    "该类商品的归类校验，无法判断是否存在归类风险。"
                ),
                related_field_keys=["hs_code"],
                related_item_ids=related,
                related_file_ids=[file_id],
                destination_country=code,
                rule_id=None,
            )

    seen_doc: set[str] = set()
    seen_item: set[tuple[str, str | None]] = set()

    for ext in extractions:
        # 票级编码（整票只有一个编码的单品名票）
        for f in ext.get("fields", []):
            if f.get("field_key") != "hs_code":
                continue
            if f.get("status") not in ("EXTRACTED", "LOW_CONFIDENCE"):
                continue
            hs = f.get("normalized_value")
            if not hs or str(hs) in seen_doc:
                continue
            seen_doc.add(str(hs))
            hs_risk(str(hs), ext["file_id"], None, doc_names.get(ext["file_id"], ext["file_id"]))

        # 品名级编码（多品名票）
        for li in ext.get("line_items") or []:
            item_id = item_of_row.get((ext["file_id"], li["item_no"]))
            for f in li.get("fields", []):
                if f.get("field_key") != "hs_code":
                    continue
                if f.get("status") not in ("EXTRACTED", "LOW_CONFIDENCE"):
                    continue
                hs = f.get("normalized_value")
                if not hs:
                    continue
                dedupe = (str(hs), item_id)
                if dedupe in seen_item:
                    continue
                seen_item.add(dedupe)
                # where 带上文件名：两份文件对同一品名给了不同编码时，
                # 两条风险的标题会完全一样，只有 detail 里的出处能区分开
                where = f"{doc_names.get(ext['file_id'], ext['file_id'])} 第 {li['item_no']} 行"
                hs_risk(str(hs), ext["file_id"], item_id, where)

    return risks
