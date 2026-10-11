"""字段抽取：把一段文本拆成契约里的 `extractions[].fields[]`。

六种状态在这里落位，**这是全项目最容易被做错的地方**：

  EXTRACTED         正常抽出，分数达标
  LOW_CONFIDENCE    抽出来了但把握不高
  NOT_IN_DOC        这份单证按规则本就没有这个字段（如装箱单没有总金额）
  MISSING_IN_DOC    按规则应该有，但文件里没找到
  UNRECOGNIZED      定位到了（比如 'G.W. *****'）但读不出值
  NORMALIZE_FAILED  读出值了但无法归一（如 'MID-OCTOBER 2026'、'未知'）

前四种必须互相区分：混在一起，界面会把所有缺失都报成警告，用户就会忽略所有警告。

关于 confidence（契约要求「给不出来给 null，不要给假的 1.0」）：
  正则抽取**没有**经过标定的概率，所以对外一律不给 confidence（保持 null）。
  匹配器返回的只是内部启发式分数 `score`，仅用来决定 EXTRACTED / LOW_CONFIDENCE
  的分档，**不写进返回体**。只有将来多模态模型给出真正标定的可信度时，
  才通过 `Found.confidence` 填进返回体。这样前端看到的每个数字都是真的。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..doc_profile import profile_of
from ..schema_fields import BY_KEY, CORE_COMPARABLE, FieldSpec
from . import normalize as N

# 内部启发式分数低于该值 => LOW_CONFIDENCE（作用于 score，不是对外 confidence）
LOW_SCORE_THRESHOLD = 0.75

# 原始片段的最长展示长度（太长前端不好展示）
MAX_RAW_LEN = 80


@dataclass
class Found:
    raw_text: str
    raw_value: str | None
    # 内部启发式分数：只用于分档，绝不写进返回体（正则无法给出标定概率）
    score: float | None
    # 经模型标定的可信度：只有多模态通道能给出；正则通道保持 None
    confidence: float | None = None
    unreadable: bool = False  # 定位到了但读不出值 => UNRECOGNIZED


# --------------------------------------------------------------------------
# 文本定位小工具
# --------------------------------------------------------------------------
def _line_of(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _tail(text: str, pos: int, window: int = 60) -> str:
    end = text.find("\n", pos)
    if end == -1 or end > pos + window:
        end = min(len(text), pos + window)
    return text[pos:end].lstrip(" \t:：.").strip()


def _clip(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return value[:MAX_RAW_LEN]


def _first_number(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"[-+]?\d[\d,.]*", text)
    return m.group(0).rstrip(".,") if m else None


def _has_unit(text: str, units: str) -> bool:
    return bool(re.search(units, text or "", re.I))


def _next_nonempty_line(text: str, pos: int) -> str:
    """标签后面没有内容时，取下一个非空行（很多单证的标签与值分两行）。"""
    rest = text[pos:]
    for line in rest.split("\n"):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


# --------------------------------------------------------------------------
# 各字段的匹配器
# --------------------------------------------------------------------------
# 标签与值之间的分隔符统一写成 `\s*[:：.]*\s*`（分隔标点允许 0 个或多个）。
# 'INVOICE NO.: xxx' 这种连着写两个标点很常见，只允许一个会让整条匹配失败，
# 字段就被误判成「该有但没找到」—— 这类静默错误正是契约要避免的。

PKG_WORD = r"(?:CARTONS?|CTNS?|CASES?|PACKAGES?|PKGS?|PALLETS?|PLTS?|BOXES?|BAGS?|DRUMS?|BUNDLES?|箱|件|托)"
KG_WORD = r"(?:KGS?|KILOGRAMS?|KILOS?|千克|公斤)"
LB_WORD = r"(?:LBS?|POUNDS?|磅)"
CBM_WORD = r"(?:CBM|M3|M³|立方米)"
PCS_WORD = r"(?:PCS|PIECES?|SETS?|UNITS?|个|件|只)"

KNOWN_CURRENCIES = (
    "USD|EUR|CNY|RMB|GBP|JPY|HKD|AUD|CAD|SGD|CHF|KRW|TWD|MYR|THB|"
    "VND|INR|RUB|NZD|SEK|NOK|DKK|PLN|AED|BRL|MXN|ZAR"
)

_PKG_PAREN = re.compile(r"\(\s*(\d{1,7})\s*\)\s*" + PKG_WORD, re.I)
_PKG_LABELED = re.compile(r"(?:TOTAL\s+)?(?:PACKAGES?|CARTONS?|PKGS?|件数)\s*[:：]*\s*(\d{1,7})", re.I)
_PKG_BARE = re.compile(r"(?<![\d.])(\d{1,7})\s*" + PKG_WORD, re.I)


def _measure_tail(text: str, pos: int) -> str:
    # 多空格可能只是数值与单位的间距；只有遇到下一字段标签才截断。
    return re.split(
        r"[ \t]{2,}(?=(?:[GN]\.?\s*W\.?|(?:GROSS|NET)\s*(?:WEIGHT|WT)|"
        r"PACKAGES?|CARTONS?|PKGS?|QTY|QUANTITY|MEAS(?:UREMENT)?\.?|VOLUME|"
        r"AMOUNT|TOTAL|毛重|净重|数量|件数|体积|金额|合计)"
        r"[ \t]*(?:[:：]|[+-]?\d|(?:" + KNOWN_CURRENCIES + r"|US\$)\b))",
        _tail(text, pos), maxsplit=1, flags=re.I,
    )[0]


def _m_packages(text: str) -> Found | None:
    for pattern, score in ((_PKG_PAREN, 0.93), (_PKG_LABELED, 0.90), (_PKG_BARE, 0.85)):
        m = pattern.search(text)
        if not m:
            continue
        line = _line_of(text, m.start())
        # 'SAY ONE HUNDRED AND TWENTY (120) CARTONS ONLY' —— 大写英文数字拼写
        # 比阿拉伯数字更容易看错，分数下调，落到 LOW_CONFIDENCE
        if re.search(r"\bSAY\b|\bONLY\b", line, re.I):
            score = round(score - 0.2, 2)
        start = m.start() if pattern is _PKG_PAREN else m.start(1)
        raw = _measure_tail(text, start)
        # ONLY 是件数大写表述的结束词；未知单位仍保留，交给归一化明确失败。
        raw = re.sub(r"\s+ONLY[ .。]*$", "", raw, flags=re.I)
        return Found(raw_text=line, raw_value=_clip(raw), score=score)
    return None


def _labeled_number(
    text: str,
    label_re: str,
    unit_re: str,
    unit_name: str,
    score_with_unit: float = 0.94,
    score_without_unit: float = 0.78,
) -> Found | None:
    m = re.search(label_re, text, re.I)
    if not m:
        return None
    line = _line_of(text, m.start())
    tail = _tail(text, m.end())
    number = _first_number(tail)
    if number is None:
        # 标签在、值读不出来
        return Found(raw_text=line, raw_value=_clip(tail) or None, score=None, unreadable=True)
    score = score_with_unit if _has_unit(tail, unit_re) else score_without_unit
    value = _clip(_measure_tail(text, m.end()))
    return Found(raw_text=line, raw_value=value or f"{number} {unit_name}", score=score)


def _m_gross_weight(text: str) -> Found | None:
    f = _labeled_number(text, r"(?<![A-Z])G\.?\s*W\.?(?![A-Z])|GROSS\s*(?:WEIGHT|WT)|毛重", KG_WORD, "KGS")
    if f:
        return f
    # 提单上常写成裸的 '2400.00 KGS'，没有 G.W. 标签，降到低把握
    m = re.search(r"(?<![\d.])(\d[\d,.]*)\s*(?:" + KG_WORD + "|" + LB_WORD + ")", text, re.I)
    if m:
        return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(m.group(0)), score=0.62)
    return None


def _m_net_weight(text: str) -> Found | None:
    return _labeled_number(text, r"(?<![A-Z])N\.?\s*W\.?(?![A-Z])|NET\s*(?:WEIGHT|WT)|净重", KG_WORD, "KGS")


def _m_volume(text: str) -> Found | None:
    return _labeled_number(
        text, r"MEAS\.?|MEASUREMENT|VOLUME|体积|尺码", CBM_WORD, "CBM", score_with_unit=0.91, score_without_unit=0.72
    )


def _m_quantity(text: str) -> Found | None:
    found = _labeled_number(
        text, r"(?<![A-Z])(?:QTY|QUANTITY)(?![A-Z])|数量", PCS_WORD, "PCS",
        score_with_unit=0.88, score_without_unit=0.74,
    )
    if found:
        return found
    # 多品名表格的合计行可以只写 TOTAL: 9600 PCS。
    m = re.search(r"^\s*(?:TOTAL|合计(?:\s*/\s*TOTAL)?|总计)\s*[:：]?\s*(\d[\d,.]*)\s*" + PCS_WORD, text, re.I | re.M)
    if m:
        return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(text[m.start(1):m.end()]), score=0.82)
    return None


def _m_hs_code(text: str) -> Found | None:
    m = re.search(
        r"(?:HS\s*CODE|H\.?S\.?|HARMONIZED\s*(?:SYSTEM\s*)?CODE|海关编码|税则号|商品编码)\s*[:：.]*\s*"
        r"([\d][\d.\-\s]{4,20})",
        text,
        re.I,
    )
    if not m:
        return None
    return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(m.group(1)), score=0.89)


def _m_total_amount(text: str) -> Found | None:
    # 数字后面不能紧跟重量/体积/数量单位 —— 否则 'G.W. TOTAL: 3,180.00 KGS'
    # 会被当成本票总金额（实测踩过：票级金额因此变成"币种未知、无法确认"）。
    NOT_A_MONEY_UNIT = (
        r"(?!\s*(?:KGS?|KILOGRAMS?|KILOS?|CBM|M3|M³|PCS|PIECES?|SETS?|UNITS?|"
        r"CTNS?|CARTONS?|CASES?|PACKAGES?|PKGS?|PALLETS?|BAGS?|DRUMS?|箱|件))"
    )
    # 严格匹配：金额必须紧跟标签（中间可以有币种），避免把
    # 'TOTAL: SAY ONE HUNDRED AND TWENTY (120) CARTONS ONLY' 里的 120 当金额
    strict = re.search(
        r"(?:TOTAL\s*(?:AMOUNT|VALUE|PRICE|CIF|FOB|INVOICE\s*VALUE)?|AMOUNT|INVOICE\s*VALUE|总金额|发票金额|合计)"
        r"\s*[:：.]*\s*(?:(?P<cur>" + KNOWN_CURRENCIES + r"|US\$)\s*)?(?P<amt>\d[\d,.]*)"
        r"(?![\d,.])"
        r"(?!\s*" + PKG_WORD + r")" + NOT_A_MONEY_UNIT,
        text,
        re.I,
    )
    if strict:
        cur = strict.group("cur")
        raw = f"{cur} {strict.group('amt')}" if cur else strict.group("amt")
        return Found(raw_text=_line_of(text, strict.start()), raw_value=_clip(raw), score=0.95)

    # 兜底：'USD 12,500.00' 这种币种+金额的写法（币种必须来自已知列表）
    loose = re.search(
        r"(?<![A-Z])(?P<cur>" + KNOWN_CURRENCIES + r"|US\$)\s*(?P<amt>\d[\d,.]*)"
        r"(?![\d,.])" + NOT_A_MONEY_UNIT,
        text,
        re.I,
    )
    if loose:
        return Found(
            raw_text=_line_of(text, loose.start()),
            raw_value=_clip(f"{loose.group('cur').upper()} {loose.group('amt')}"),
            score=0.80,
        )
    return None


def _m_currency(text: str) -> Found | None:
    us_symbol = re.search(r"(?<![A-Z])US\$", text, re.I)
    if us_symbol:
        return Found(raw_text=_line_of(text, us_symbol.start()), raw_value="US$", score=0.97)
    m = re.search(r"\b(" + KNOWN_CURRENCIES + r")\b", text, re.I)
    if not m:
        return None
    return Found(raw_text=_line_of(text, m.start()), raw_value=m.group(1).upper(), score=0.97)


DESC_LABEL = (
    r"(?:DESCRIPTION\s*(?:OF\s*GOODS)?|GOODS\s*DESCRIPTION|COMMODITY|NAME\s*OF\s*COMMODITY|"
    r"品名|货物描述|商品名称|货名)"
)

# 兜底用的「标签词」，避免把别的字段行误当成货物描述
_OTHER_LABEL_WORDS = re.compile(
    r"INVOICE|PACKING|LADING|SHIPPER|CONSIGNEE|PORT|CONTRACT|B/L|NO\.|DATE|TOTAL|AMOUNT|"
    r"WEIGHT|G\.?W|N\.?W|MEAS|QTY|QUANTITY|HS\s*CODE|CERTIFICATE|POLICY|COUNTRY",
    re.I,
)


def _m_description(text: str) -> Found | None:
    m = re.search(DESC_LABEL + r"\s*[:：.]*\s*", text, re.I)
    if m:
        tail = _tail(text, m.end(), window=80)
        if not tail:
            tail = _next_nonempty_line(text, m.end())
        if tail:
            return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(tail), score=0.93)

    # 没有标签时，找一行「看起来像货名」的大写行，把握必须压低
    for line in text.split("\n"):
        stripped = line.strip()
        if len(stripped) < 8 or _OTHER_LABEL_WORDS.search(stripped):
            continue
        letters = [c for c in stripped if c.isalpha()]
        if len(letters) < 6:
            continue
        if sum(1 for c in letters if c.isupper()) / len(letters) < 0.85:
            continue
        if len(stripped.split()) < 2:
            continue
        return Found(raw_text=stripped, raw_value=_clip(stripped), score=0.55)
    return None


def _m_invoice_no(text: str) -> Found | None:
    m = re.search(
        r"(?:INVOICE\s*(?:NO|NUM|NUMBER|#)|发票号|发票编号)\s*[:：.]*\s*([A-Za-z0-9][A-Za-z0-9\-/]{2,30})",
        text,
        re.I,
    )
    if not m:
        return None
    return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(m.group(1)), score=0.98)


def _m_shipment_date(text: str) -> Found | None:
    m = re.search(
        r"(?:SHIPPED\s+ON\s+BOARD|SHIPMENT\s+DATE|SHIPPING\s+DATE|ON\s+BOARD\s+DATE|"
        r"装运日期|装船日期|出运日期)\s*[:：.]*\s*([^\n]{4,30})",
        text,
        re.I,
    )
    if not m:
        return None
    return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(m.group(1)), score=0.92)


def _m_bill_of_lading_no(text: str) -> Found | None:
    m = re.search(
        r"(?:B/L\s*(?:NO|NUM|NUMBER|#)|BILL\s+OF\s+LADING\s*(?:NO|NUM|NUMBER|#)|提单号)\s*[:：.]*\s*"
        r"([A-Za-z0-9][A-Za-z0-9\-]{3,30})",
        text,
        re.I,
    )
    if not m:
        return None
    return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(m.group(1)), score=0.96)


def _m_contract_no(text: str) -> Found | None:
    m = re.search(
        r"(?:CONTRACT\s*(?:NO|NUM|NUMBER|#)|S/?C\s*NO|合同号)\s*[:：.]*\s*([A-Za-z0-9][A-Za-z0-9\-/]{2,30})",
        text,
        re.I,
    )
    if not m:
        return None
    return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(m.group(1)), score=0.94)


def _m_container_no(text: str) -> Found | None:
    m = re.search(r"\b([A-Z]{4}\d{7})\b", text)
    if not m:
        return None
    return Found(raw_text=_line_of(text, m.start()), raw_value=m.group(1), score=0.90)


def _m_shipper(text: str) -> Found | None:
    return _labeled_text(text, r"(?:SHIPPER|发货人|卖方|SELLER)")


def _m_consignee(text: str) -> Found | None:
    return _labeled_text(text, r"(?:CONSIGNEE|收货人|买方|BUYER)")


def _m_port_of_loading(text: str) -> Found | None:
    f = _labeled_text(text, r"(?:PORT\s+OF\s+LOADING|PORT\s+OF\s+DEPARTURE|POL|起运港|装货港)")
    if f:
        return f
    m = re.search(r"^\s*(?:FROM|起运)\s*[:：]*\s*([A-Z][A-Za-z\s,]{2,40})$", text, re.M)
    if m:
        return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(m.group(1)), score=0.80)
    return None


def _m_port_of_discharge(text: str) -> Found | None:
    f = _labeled_text(text, r"(?:PORT\s+OF\s+DISCHARGE|PORT\s+OF\s+DESTINATION|POD|目的港|卸货港)")
    if f:
        return f
    m = re.search(r"^\s*(?:TO|目的港)\s*[:：]*\s*([A-Z][A-Za-z\s,]{2,40})$", text, re.M)
    if m:
        return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(m.group(1)), score=0.80)
    return None


def _m_destination_country(text: str) -> Found | None:
    f = _labeled_text(
        text, r"(?:DESTINATION\s+(?:COUNTRY|PORT)?|COUNTRY\s+OF\s+DESTINATION|目的国|目的地)"
    )
    if f:
        return f
    # 兜底：整行就是一个大写国名的情形；认不出就不认，不猜
    for m in re.finditer(r"^\s*([A-Z][A-Z ]{3,30})\s*$", text, re.M):
        if N.to_country(m.group(1)):
            return Found(raw_text=m.group(1).strip(), raw_value=_clip(m.group(1)), score=0.70)
    return None


def _labeled_text(text: str, label_re: str) -> Found | None:
    """标签 + 同行的值；同行没值就取下一行。"""
    m = re.search(label_re + r"\s*[:：.]*\s*", text, re.I)
    if not m:
        return None
    tail = _tail(text, m.end(), window=80)
    if not tail:
        tail = _next_nonempty_line(text, m.end())
    if not tail or _OTHER_LABEL_WORDS.fullmatch(tail):
        return None
    return Found(raw_text=_line_of(text, m.start()), raw_value=_clip(tail), score=0.90)


MATCHERS = {
    "packages": _m_packages,
    "gross_weight": _m_gross_weight,
    "net_weight": _m_net_weight,
    "volume": _m_volume,
    "quantity": _m_quantity,
    "hs_code": _m_hs_code,
    "total_amount": _m_total_amount,
    "currency": _m_currency,
    "description": _m_description,
    "invoice_no": _m_invoice_no,
    "shipment_date": _m_shipment_date,
    "bill_of_lading_no": _m_bill_of_lading_no,
    "contract_no": _m_contract_no,
    "container_no": _m_container_no,
    "shipper": _m_shipper,
    "consignee": _m_consignee,
    "port_of_loading": _m_port_of_loading,
    "port_of_discharge": _m_port_of_discharge,
    "destination_country": _m_destination_country,
}


# --------------------------------------------------------------------------
# 归一：字段 -> (归一函数, 数据来源说明)
# --------------------------------------------------------------------------
def _norm_number(raw: str | None):
    return N.to_number(raw), None


def _norm_hs(raw: str | None):
    return N.to_hs_code(raw), None


def _norm_currency(raw: str | None):
    return N.to_currency(raw), None


def _norm_date(raw: str | None):
    return N.to_date(raw), None


def _norm_description(raw: str | None):
    return N.normalize_description(raw), None


def _norm_port(raw: str | None):
    return N.to_port(raw), None


def _norm_country(raw: str | None):
    return N.to_country(raw), None


def _norm_text(raw: str | None):
    return N.to_text(raw), None


NORMALIZERS = {
    "packages": _norm_number,
    "gross_weight": _norm_number,
    "net_weight": _norm_number,
    "volume": _norm_number,
    "quantity": _norm_number,
    "total_amount": _norm_number,
    "hs_code": _norm_hs,
    "currency": _norm_currency,
    "shipment_date": _norm_date,
    "description": _norm_description,
    "port_of_loading": _norm_port,
    "port_of_discharge": _norm_port,
    "destination_country": _norm_country,
}


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------
def extract_fields(
    text: str,
    doc_type: str | None,
    page: int | None = 1,
    row_keys: set[str] | None = None,
) -> list[dict]:
    """返回契约 `Extraction.fields`（**票级**）的字典列表。

    `row_keys` 是这份文件表格里**按行提供**的字段（如表头里的 DESCRIPTION / HS CODE / QTY）。
    多品名票里这些项由各品名行承担（见 line_items[]），票级报 NOT_IN_DOC 而不是
    MISSING_IN_DOC —— 「这一票的货物描述」对多品名票本身就不成立，报成「该有没找到」
    会刷出一堆假缺失，把真缺失淹没。
    """
    found: dict[str, Found] = {}
    for key, matcher in MATCHERS.items():
        if key == "description" and row_keys and "description" in row_keys:
            continue
        try:
            f = matcher(text)
        except Exception:  # noqa: BLE001  单个匹配器出错不该拖垮整份文件
            f = None
        if f is not None:
            found[key] = f

    profile = profile_of(doc_type)
    if profile is None:
        # 判不出单证类型：只报抽到的，不臆测「应该有 / 本就不适用」
        keys = list(found.keys())
    else:
        core_keys = [s.key for s in CORE_COMPARABLE]
        extra = [k for k in found if k not in core_keys]
        keys = core_keys + sorted(extra)

    currency_value = _normalized_of(found, "currency")
    fields: list[dict] = []

    for key in keys:
        spec: FieldSpec = BY_KEY[key]
        f = found.get(key)
        unit = spec.unit

        if f is None:
            # 没抽到就没有位置信息，page 给 null，不编造
            if row_keys and key in row_keys:
                status = "NOT_IN_DOC"
                note: str | None = "本单证为多品名，该项按品名行给出（见 line_items[]），票级不适用。"
            elif profile and key in profile:
                status = "MISSING_IN_DOC"
                note = None
            else:
                status = "NOT_IN_DOC"
                note = None
            fields.append(_field(spec, status=status, page=None, unit=unit, raw_text=note))
            continue

        if f.unreadable:
            fields.append(
                _field(
                    spec,
                    status="UNRECOGNIZED",
                    raw_text=f.raw_text,
                    raw_value=f.raw_value,
                    page=page,
                    unit=unit,
                )
            )
            continue

        if key in {"packages", "quantity", "gross_weight", "net_weight", "volume"}:
            normalized, detected_unit = N.to_measure(f.raw_value, key)
            unit = detected_unit
        else:
            normalizer = NORMALIZERS.get(key, _norm_text)
            normalized, _ = normalizer(f.raw_value)

        if normalized is None:
            fields.append(
                _field(
                    spec,
                    status="NORMALIZE_FAILED",
                    raw_text=f.raw_text,
                    raw_value=f.raw_value,
                    page=page,
                    unit=unit,
                )
            )
            continue

        if key == "total_amount":
            # 金额的单位是币种：优先取本文件里抽到的币种
            unit = currency_value or N.to_currency(f.raw_value)

        # 分档只依据内部启发式分数；对外 confidence 只写模型标定值（正则通道为 null）
        score = f.score
        status = "EXTRACTED" if (score is not None and score >= LOW_SCORE_THRESHOLD) else "LOW_CONFIDENCE"
        fields.append(
            _field(
                spec,
                status=status,
                raw_text=f.raw_text,
                raw_value=f.raw_value,
                normalized_value=normalized,
                confidence=f.confidence,
                page=page,
                unit=unit,
            )
        )

    return fields


def _normalized_of(found: dict[str, Found], key: str):
    f = found.get(key)
    if f is None or f.raw_value is None:
        return None
    normalizer = NORMALIZERS.get(key, _norm_text)
    return normalizer(f.raw_value)[0]


def _field(
    spec: FieldSpec,
    status: str,
    raw_text: str | None = None,
    raw_value: str | None = None,
    normalized_value=None,
    confidence: float | None = None,
    page: int | None = 1,
    unit: str | None = None,
) -> dict:
    """构造一条 Field。契约要求 8 个键必须存在，用不到的显式给 null。"""
    return {
        "field_key": spec.key,
        "label": spec.label,
        "raw_text": raw_text,
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "unit": unit,
        "confidence": confidence,
        "status": status,
        # 我们没有做版式定位，page 只能给单页文件的确定值，其余留 null，不编造
        "page": page,
        "bbox": None,
        "bbox_unit": None,
    }
