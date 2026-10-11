"""归一化：把单证上五花八门的写法，变成可比较的值。

契约第九节：缺失值用 null，**不使用空字符串**（空字符串无法区分
「未抽取到」与「抽取到但内容为空」）。
"""

from __future__ import annotations

import re
from datetime import datetime

# --------------------------------------------------------------------------
# 数字
# --------------------------------------------------------------------------
_NUMBER_TOKEN = re.compile(r"[-+]?\d[\d,.]*")

_MEASURE_UNITS = {
    "quantity": ("PCS", r"PCS|PIECES?|UNITS?|个|只", 1),
    "packages": ("CARTON", r"CARTONS?|CTNS?|箱", 1),
    "gross_weight": ("KGS", r"KGS?|KILOGRAMS?|KILOS?|千克|公斤", 1),
    "net_weight": ("KGS", r"KGS?|KILOGRAMS?|KILOS?|千克|公斤", 1),
    "volume": ("CBM", r"CBM|M3|M³|立方米", 1),
}


def to_measure(raw: str | None, field_key: str) -> tuple[int | float | None, str | None]:
    """数值与原单位一起归一；未知单位不按默认单位冒充成功。"""
    default, aliases, factor = _MEASURE_UNITS[field_key]
    if raw is None:
        return None, None
    text = str(raw).strip()
    match = _NUMBER_TOKEN.search(text)
    if not match:
        return None, None
    number = to_number(match.group(0))
    if number is None:
        return None, None
    suffix = text[match.end():].strip(" .:：,，")
    if not suffix:
        return number, default  # 没写单位时沿用该字段约定的默认单位
    if re.fullmatch(rf"(?:{aliases})(?:\s*[（(]\s*(?:{aliases})\s*[）)])?", suffix, re.I):
        return number * factor, default
    if field_key in {"gross_weight", "net_weight"} and re.fullmatch(r"LBS?|POUNDS?|磅", suffix, re.I):
        return round(number * 0.45359237, 6), default
    return None, None


def to_number(raw: str | None) -> int | float | None:
    """'2,400.00 KGS' / '12.500' / '120 CARTONS' -> 2400.0 / 12.5 / 120"""
    if raw is None:
        return None
    text = str(raw).strip()
    # 中文/英文的「若干、未知、待定」这类非数值表述，归一必须失败
    if re.search(r"未知|待定|若干|不详|待确认|N/?A|UNKNOWN|TBD|VARIOUS", text, re.I):
        return None
    m = _NUMBER_TOKEN.search(text)
    if not m:
        return None
    token = m.group(0).rstrip(".,")
    if "." in token and "," in token:
        # 最后出现的分隔符是小数点；另一种分隔符是千位符。
        decimal = "." if token.rfind(".") > token.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        integer, fraction = token.rsplit(decimal, 1)
        groups = integer.lstrip("+-").split(thousands)
        if not fraction.isdigit() or len(fraction) > 2 or (
            len(groups) > 1 and (not 1 <= len(groups[0]) <= 3 or any(len(g) != 3 for g in groups[1:]))
        ):
            return None
        cleaned = integer.replace(thousands, "") + "." + fraction
    elif "," in token:
        groups = token.lstrip("+-").split(",")
        if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]):
            cleaned = token.replace(",", "")
        elif len(groups) == 2 and 1 <= len(groups[1]) <= 2:
            cleaned = token.replace(",", ".")
        else:
            return None
    else:
        cleaned = token
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


# --------------------------------------------------------------------------
# HS 编码
# --------------------------------------------------------------------------
def to_hs_code(raw: str | None) -> str | None:
    """'6911.10.00' / '6911 10 00' -> '6911100000'（只留数字）"""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) < 6 or len(digits) > 12:
        return None
    return digits


# --------------------------------------------------------------------------
# 日期
# --------------------------------------------------------------------------
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y%m%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
)

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def to_date(raw: str | None) -> str | None:
    """统一成 ISO 日期 YYYY-MM-DD。解析不了返回 None（=> NORMALIZE_FAILED）。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    # 'MID-OCTOBER 2026' 这种模糊表述不能猜 —— 猜出来的日期是伪造数据
    if re.search(r"MID|EARLY|LATE|ABOUT|AROUND|约|上旬|中旬|下旬", text, re.I):
        return None

    # 两段都 <=12 的数字日期同时符合日/月与月/日，缺少地区约定时不能猜。
    numeric = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if numeric and int(numeric.group(1)) <= 12 and int(numeric.group(2)) <= 12:
        return None

    chinese = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if chinese:
        try:
            return datetime(*(int(x) for x in chinese.groups())).strftime("%Y-%m-%d")
        except ValueError:
            return None

    for fmt in _DATE_FORMATS:
        try:
            # 只把待解析文本转大写（让 'OCT' 这类月份能匹配），
            # 格式串必须原样 —— 把 %m/%d 也转成大写会变成 %M（分钟）/%D，直接解析失败
            return datetime.strptime(text.upper(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # '08 OCT 2026' 里夹了多余内容时，抓出日/月/年三段再拼
    m = re.search(r"(\d{1,2})\s*[-\s]\s*([A-Z]{3,9})\.?\s*[-\s]\s*(\d{4})", text.upper())
    if m:
        mon = _MONTHS.get(m.group(2)[:3])
        if mon:
            try:
                return datetime(int(m.group(3)), mon, int(m.group(1))).strftime("%Y-%m-%d")
            except ValueError:
                return None
    return None


# --------------------------------------------------------------------------
# 币种
# --------------------------------------------------------------------------
_CURRENCY_ALIAS = {
    "RMB": "CNY",
    "YUAN": "CNY",
    "人民币": "CNY",
    "美元": "USD",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "欧元": "EUR",
    "日元": "JPY",
    "港币": "HKD",
    "港元": "HKD",
}


def to_currency(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if re.search(r"(?<![A-Z])US\$", text):
        return "USD"
    m = re.search(r"\b([A-Z]{3})\b", text)
    if m:
        return _CURRENCY_ALIAS.get(m.group(1), m.group(1))
    for key, code in _CURRENCY_ALIAS.items():
        if key in text:
            return code
    return None


# --------------------------------------------------------------------------
# 文本类：货物描述
# --------------------------------------------------------------------------
# 这是一份「最小词表」，让不同写法的同一件货归一后能对上。
# 契约里 description 是 STRING，比对时用词集相似度，不要求逐字相同。
DESCRIPTION_GLOSSARY = {
    "CERAMIC": "陶瓷", "PORCELAIN": "陶瓷", "MUG": "马克杯", "CUP": "杯",
    "SAUCER": "碟", "PLATE": "盘", "BOWL": "碗", "TABLEWARE": "餐具",
    "KITCHENWARE": "厨具", "STAINLESS": "不锈钢", "STEEL": "钢",
    "ALUMINUM": "铝", "IRON": "铁", "GLASS": "玻璃", "PLASTIC": "塑料",
    "BAMBOO": "竹", "WOODEN": "木质", "WOOD": "木", "PAPER": "纸",
    "COTTON": "棉", "FABRIC": "面料", "TOWEL": "毛巾", "BLANKET": "毯",
    "SHIRT": "衬衫", "T-SHIRT": "T恤", "JACKET": "夹克", "BAG": "袋",
    "BACKPACK": "背包", "BOTTLE": "瓶", "FLASK": "壶", "LAMP": "灯",
    "TOY": "玩具", "SET": "套装", "GIFT": "礼品", "BOX": "盒",
    "WHITE": "白", "BLACK": "黑", "BLUE": "蓝", "RED": "红",
    "GREEN": "绿", "GLAZE": "釉",
}


def normalize_description(raw: str | None) -> str | None:
    """把描述切成词，查词表翻译，去掉重复，保持原顺序拼回。

    'CERAMIC MUG 350ML WHITE'      -> '陶瓷 马克杯 350ML 白'
    'CERAMIC MUG, 350ML, WHITE GLAZE' -> '陶瓷 马克杯 350ML 白 釉'
    两条不是逐字相同，但词集高度重合，比对时按相似度判为 MATCH。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    tokens: list[str] = []
    for tok in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text.upper()):
        if not tok:
            continue
        out = DESCRIPTION_GLOSSARY.get(tok, tok)
        if out not in tokens:
            tokens.append(out)
    return " ".join(tokens) if tokens else None


def token_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {t for t in re.split(r"\s+", value) if t}


# --------------------------------------------------------------------------
# 文本类：地名
# --------------------------------------------------------------------------
PORT_GLOSSARY = {
    "SHANGHAI": "上海", "NINGBO": "宁波", "SHENZHEN": "深圳", "QINGDAO": "青岛",
    "TIANJIN": "天津", "XIAMEN": "厦门", "GUANGZHOU": "广州", "HONG KONG": "中国香港",
    "HAMBURG": "汉堡", "ROTTERDAM": "鹿特丹", "ANTWERP": "安特卫普",
    "LE HAVRE": "勒阿弗尔", "FELIXSTOWE": "费利克斯托",
    "LOS ANGELES": "洛杉矶", "LONG BEACH": "长滩", "NEW YORK": "纽约",
    "SINGAPORE": "新加坡", "BUSAN": "釜山", "TOKYO": "东京", "YOKOHAMA": "横滨",
}

COUNTRY_GLOSSARY = {
    "GERMANY": "DE", "DE": "DE", "德国": "DE",
    "UNITED STATES": "US", "USA": "US", "U.S.A": "US", "US": "US", "美国": "US",
    "CHINA": "CN", "CN": "CN", "中国": "CN", "P.R.CHINA": "CN",
    "NETHERLANDS": "NL", "HOLLAND": "NL", "NL": "NL", "荷兰": "NL",
    "FRANCE": "FR", "FR": "FR", "法国": "FR",
    "UNITED KINGDOM": "GB", "UK": "GB", "GB": "GB", "英国": "GB",
    "JAPAN": "JP", "JP": "JP", "日本": "JP",
    "SPAIN": "ES", "ES": "ES", "西班牙": "ES",
    "ITALY": "IT", "IT": "IT", "意大利": "IT",
    "POLAND": "PL", "PL": "PL", "波兰": "PL",
    "BELGIUM": "BE", "BE": "BE", "比利时": "BE",
    "VIETNAM": "VN", "VN": "VN", "越南": "VN",
    "KOREA": "KR", "SOUTH KOREA": "KR", "KR": "KR", "韩国": "KR",
}


# 国别代码 -> 中文名。POST 没带 destination_country_name 时用它补上。
CODE_TO_NAME = {
    "DE": "德国", "US": "美国", "CN": "中国", "NL": "荷兰", "FR": "法国",
    "GB": "英国", "JP": "日本", "ES": "西班牙", "IT": "意大利", "PL": "波兰",
    "BE": "比利时", "VN": "越南", "KR": "韩国", "SG": "新加坡", "AU": "澳大利亚",
}


def country_name(code: str | None) -> str | None:
    if not code:
        return None
    return CODE_TO_NAME.get(code.upper())


def _clean_place(raw: str | None) -> str:
    text = re.sub(r"\s+", " ", str(raw or "").strip())
    text = text.strip(" ,;。.")
    return text


def to_port(raw: str | None) -> str | None:
    """'HAMBURG, GERMANY' -> '汉堡'；词表里没有就取第一段地名。"""
    text = _clean_place(raw)
    if not text:
        return None
    upper = text.upper()
    for name, cn in PORT_GLOSSARY.items():
        if name in upper:
            return cn
    first = re.split(r"[,，/]", text)[0].strip()
    return first.upper() if first else None


def to_country(raw: str | None) -> str | None:
    """'HAMBURG, GERMANY' / 'GERMANY' / 'DE' -> 'DE'"""
    text = _clean_place(raw)
    if not text:
        return None
    upper = text.upper()
    for name in sorted(COUNTRY_GLOSSARY, key=len, reverse=True):
        if re.search(rf"(?<![A-Z]){re.escape(name)}(?![A-Z])", upper):
            return COUNTRY_GLOSSARY[name]
    return None


# --------------------------------------------------------------------------
# 通用文本
# --------------------------------------------------------------------------
def to_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = re.sub(r"\s+", " ", str(raw).strip()).strip(" ,;。.")
    return text.upper() if text else None
