"""Project exchange format; deliberately not an EDIFACT/X12 adapter."""
import json

from ..schema_fields import BY_KEY, CORE_COMPARABLE, IDENTIFIERS, ITEM_LEVEL_BY_KEY
from ..doc_profile import profile_of
from .extract import NORMALIZERS, _field, _norm_text
from . import normalize as N

FORMAT = "hackathon-trade-json-v1"
DOC_TYPES = {"COMMERCIAL_INVOICE", "PACKING_LIST", "BILL_OF_LADING"}
DOC_KEYS = {s.key for s in CORE_COMPARABLE + IDENTIFIERS}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 键：{key}")
        result[key] = value
    return result


def _keys(obj, allowed, required):
    if not isinstance(obj, dict) or set(obj) - allowed or not required <= set(obj):
        raise ValueError("对象缺少必填键或含不支持的键")


def _fields(values, allowed, currency=None):
    if not isinstance(values, dict) or set(values) - allowed:
        raise ValueError("不支持的字段")
    result = []
    for key, raw in values.items():
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000:
            raise ValueError("字段必须是 1–2000 字符的原始字符串")
        if key in {"packages", "quantity", "gross_weight", "net_weight", "volume"}:
            value, unit = N.to_measure(raw, key)
        elif key in {"amount", "unit_price"}:
            value, unit = N.to_number(raw), currency
        else:
            value, _ = NORMALIZERS.get(key, _norm_text)(raw)
            unit = currency if key == "total_amount" else BY_KEY[key].unit
        result.append(_field(BY_KEY[key], "EXTRACTED" if value is not None else "NORMALIZE_FAILED",
                             raw_text=f"{key}: {raw}", raw_value=raw, normalized_value=value,
                             page=None, unit=unit))
    return result


def parse_trade_json(data):
    if len(data) > 1024 * 1024:
        raise ValueError("项目交换 JSON 最大 1 MiB")
    obj = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique,
                     parse_constant=lambda value: (_ for _ in ()).throw(ValueError("非有限数字")))
    _keys(obj, {"format", "doc_type", "fields", "line_items"}, {"format", "doc_type", "fields"})
    if obj["format"] != FORMAT or obj["doc_type"] not in DOC_TYPES:
        raise ValueError("仅支持 hackathon-trade-json-v1 的发票、装箱单、提单；不支持标准 EDIFACT/X12")
    if not isinstance(obj["fields"], dict) or any(not isinstance(value, str) for value in obj["fields"].values()):
        raise ValueError("票级字段必须是字符串对象")
    currency = N.to_currency(obj["fields"].get("currency"))
    fields = _fields(obj["fields"], DOC_KEYS, currency)
    rows = obj.get("line_items", [])
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("商品行必须是数组，最多 200 行")
    lines, seen = [], set()
    for row in rows:
        _keys(row, {"item_no", "fields"}, {"item_no", "fields"})
        number = row["item_no"]
        if type(number) is not int or number < 1 or number in seen:
            raise ValueError("商品行号必须为不重复的正整数")
        seen.add(number)
        if not isinstance(row["fields"], dict) or not {"description", "item_code"} <= set(row["fields"]):
            raise ValueError("商品行必须包含货号和描述")
        row_fields = _fields(row["fields"], set(ITEM_LEVEL_BY_KEY), currency)
        for key in sorted(set(ITEM_LEVEL_BY_KEY) - set(row["fields"])):
            row_fields.append(_field(ITEM_LEVEL_BY_KEY[key],
                "MISSING_IN_DOC" if key in (profile_of(obj["doc_type"]) or set()) else "NOT_IN_DOC", page=None))
        lines.append({"item_no": number, "raw_text": json.dumps(row, ensure_ascii=False), "fields": row_fields})
    present = {f["field_key"] for f in fields}
    row_keys = {f["field_key"] for row in lines for f in row["fields"]}
    for spec in CORE_COMPARABLE:
        if spec.key not in present:
            required = spec.key in (profile_of(obj["doc_type"]) or {}) and spec.key not in row_keys
            fields.append(_field(spec, "MISSING_IN_DOC" if required else "NOT_IN_DOC", page=None, unit=spec.unit))
    return {"doc_type": obj["doc_type"], "fields": fields, "line_items": lines}
