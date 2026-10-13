"""行切分：把一份单证的表格区域拆成 `LineItem`（v0.2 第 1.5 层的一半）。

为什么必须单独做，而不是继续用整页正则：
单品名单证是「标签 + 值」的一维结构，正则够用。多品名单证是二维的 ——
同一页里有 4 个品名，每个品名各自有一份件数/毛重/金额。整页正则只会抓到
**第一个**（往往是表头或行号），然后拿着垃圾去比对，给出一个看起来很正常的
错误结论。这就是我们在多品名探针里实测到的：

    total_amount 抽到 "1."（行号）、description 抽到 "QTY UNIT PRICE AMOUNT"（表头）

本模块做两件事：

1. `split_table()` —— 认出表格区域，并把它**从票级文本里剥掉**。
   剥掉之后票级抽取就不会再抓到表头和行号了。合计行（TOTAL）保留，
   因为整票合计本身就是票级字段。
2. `parse_line_items()` —— 按「≥2 个空格」切单元格（版面表格），切不动就退回
   正则（松散文本）。**用表头决定这一行该有哪些字段**：
   表头里有这一列但单元格是空的 → MISSING_IN_DOC；表头里没有这一列 → NOT_IN_DOC。
   这样「本就不适用」和「该有没抽到」在行级也是分开的。

已知边界（写进 README，不假装支持）：
  - 只处理文本层 PDF。扫描件/图片要等 OCR 通道。
  - 单元格靠空白切分，所以依赖版式里列间有多空格。挤在一起的行会走正则兜底，
    描述里若含 `24PCS` 这类片段可能被误切成数量列 —— 这类票会被标成
    `suspect`，由上层降级为 NOT_CHECKED，不会静默给出错误结论。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schema_fields import ITEM_LEVEL, ITEM_LEVEL_BY_KEY, FieldSpec
from . import normalize as N

# 行首序号：'1'、'1.'、'1)'、'01'
ROW_START = re.compile(r"^\s*(\d{1,3})\s*[.)]?\s+(?=\S)")

# 合计行 —— 属于票级，不算品名行，且要保留给票级抽取
TOTAL_LINE = re.compile(r"^\s*(?:TOTAL|SAY|SUB\s*-?\s*TOTAL|GRAND\s+TOTAL|合计|总计|总件数)\b", re.I)

# 表格区域的起止：以 TOTAL 行为界，或连续 40 行内没有新行
MAX_ROWS = 200

# 表头关键词 → 行级 field_key。用于判断「这一行该有哪些字段」。
HEADER_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"SKU|ITEM\s*(?:NO|NUM|CODE)|ART\.?\s*(?:NO|CODE)|MODEL|货号|型号|商品编码", re.I), "item_code"),
    (re.compile(r"DESCRIPTION(?:\s+OF\s+GOODS|\s*/\s*SKU)?|GOODS|COMMODITY|品名|货物描述", re.I), "description"),
    (re.compile(r"HS\s*CODE|H\.?\s*S\.?|TARIFF|税则号", re.I), "hs_code"),
    (re.compile(r"\bQTY\b|QUANTITY|数量", re.I), "quantity"),
    (re.compile(r"PACKAGES?|PKGS?|CARTONS?|CTNS?|CASES?|件数", re.I), "packages"),
    (re.compile(r"N\.?\s*W\.?|NET\s*(?:WEIGHT|WT|KG)|净重", re.I), "net_weight"),
    (re.compile(r"G\.?\s*W\.?|GROSS\s*(?:WEIGHT|WT|KG)|毛重", re.I), "gross_weight"),
    (re.compile(r"MEAS|VOLUME|CBM|体积", re.I), "volume"),
    (re.compile(r"UNIT\s*PRICE|单价", re.I), "unit_price"),
    (re.compile(r"AMOUNT(?:\s*\([A-Z]{3}\))?|VALUE|金额", re.I), "amount"),
]

# 松散文本兜底用：从整行里找各类值
_HS_RE = re.compile(r"\b(\d{4}[.\s]?\d{2}(?:[.\s]?\d{2,4})?)\b")
_QTY_RE = re.compile(r"(\d[\d,]*)\s*(?:PCS|PIECES?|SETS?|UNITS?|个|只)", re.I)
_PKG_RE = re.compile(r"(\d[\d,]*)\s*(?:CARTONS?|CTNS?|CASES?|PACKAGES?|PKGS?|PALLETS?|箱)", re.I)
_KG_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:KGS?|KILOGRAMS?)", re.I)
_CBM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:CBM|M3|M³)", re.I)
_MONEY_RE = re.compile(
    r"(?:(?P<cur>[A-Z]{3})\s*)?(?P<amt>\d[\d,]*(?:\.\d{1,2})?)", re.I
)
_ITEM_CODE_RE = re.compile(r"^[A-Z]{1,6}[-/]?\d{2,8}[A-Z]?$", re.I)

CELL_SPLIT = re.compile(r"\s{2,}")
# Internal placeholder used by the HTML table adapter to preserve empty cells.
EMPTY_CELL = "\ue000"


@dataclass
class TableResult:
    line_items: list[dict] = field(default_factory=list)
    doc_text: str = ""
    header_keys: set[str] = field(default_factory=set)
    has_table: bool = False
    # 疑似品名行但没能解析成结构化字段 —— 上层据此降级，不静默给结论
    suspected: bool = False


# --------------------------------------------------------------------------
# 1) 找到表格区域并从票级文本里剥掉
# --------------------------------------------------------------------------
def _looks_like_header(line: str) -> set[str]:
    """一行里命中 ≥3 个表头列名才算表头，避免把普通文本行认成表头。"""
    hits: set[str] = set()
    for pattern, key in HEADER_MAP:
        if pattern.search(line):
            hits.add(key)
    return hits if len(hits) >= 3 else set()


def _header_columns(line: str) -> list[str]:
    """只接受能按列切开的表头，保留单证原有列序。"""
    columns: list[str] = []
    for cell in CELL_SPLIT.split(line.strip()):
        matches = [key for pattern, key in HEADER_MAP if pattern.fullmatch(cell.strip().rstrip("."))]
        if len(matches) == 1:
            if matches[0] in columns:
                return []
            columns.append(matches[0])
        elif cell.strip().upper() not in {"NO.", "NO", "序号"}:
            return []
    return columns if len(columns) >= 3 else []


def split_table(text: str) -> tuple[str, list[str], list[str]]:
    """返回 (剥掉表格后的票级文本, 表格行原文, 表头列集合)。

    合计行故意保留在票级文本里 —— 整票合计是票级字段，不是品名行。
    """
    lines = text.split("\n")
    header_at: int | None = None
    header_order: list[str] = []

    if len(lines) > 400:
        # 保住性能，同时保证 lines 的下标与原件一致（用短行占位）
        lines = [ln[:400] for ln in lines]

    for i, line in enumerate(lines[:400]):
        keys = _looks_like_header(line)
        if keys:
            header_at = i
            header_order = _header_columns(line)
            break

    if header_at is None:
        return text, [], []

    rows: list[str] = []
    end = len(lines)
    # 多看一行，区分刚好达到上限与仍有正文未读；超限时由解析层明确降级。
    for j in range(header_at + 1, min(len(lines), header_at + 2 + MAX_ROWS)):
        line = lines[j]
        if TOTAL_LINE.match(line):
            end = j
            break
        rows.append(line)

    kept = lines[:header_at] + lines[end:]
    return "\n".join(kept), rows, header_order


# --------------------------------------------------------------------------
# 2) 单行解析
# --------------------------------------------------------------------------
def _cells(line: str) -> list[str]:
    """按 ≥2 个空格切单元格；切不动返回空列表。"""
    stripped = ROW_START.sub("", line.strip(), count=1)
    parts = ["" if p.strip() == EMPTY_CELL else p.strip() for p in CELL_SPLIT.split(stripped)]
    return parts if len(parts) >= 2 else []


def _number_of(cell: str | None) -> str | None:
    if not cell:
        return None
    m = re.search(r"[-+]?\d[\d,.]*", cell)
    return m.group(0) if m else None


def _assign_from_cells(parts: list[str], header_order: list[str]) -> dict[str, str]:
    """按表头顺序把单元格分给各列。

    表头数量与单元格数量对不上时（多空格/缺列），退化为「按值的样子猜列」，
    这种行会被记成低分，不当作可靠抽取。
    """
    out: dict[str, str] = {}
    if header_order and len(parts) == len(header_order):
        for key, value in zip(header_order, parts):
            out[key] = value
        return out

    # 单元格里第一个像货号的优先给 item_code
    rest = list(parts)
    if "item_code" in header_order and rest and _ITEM_CODE_RE.match(rest[0].split()[0]):
        out["item_code"] = rest.pop(0)
    for cell in rest:
        low = cell.lower()
        if "hs_code" not in out and _HS_RE.fullmatch(cell.strip()) is None:
            m = _HS_RE.search(cell)
            if m and re.fullmatch(r"[\d.\s]+", cell.strip()):
                out["hs_code"] = cell
                continue
        if "description" not in out and not _number_of(cell):
            out["description"] = cell
            continue
        if "quantity" not in out and _QTY_RE.search(cell):
            out["quantity"] = cell
            continue
        if "packages" not in out and _PKG_RE.search(cell):
            out["packages"] = cell
            continue
        if "net_weight" not in out and re.search(r"N\.?\s*W", cell, re.I):
            out["net_weight"] = cell
            continue
        if "gross_weight" not in out and _KG_RE.search(cell):
            out["gross_weight"] = cell
            continue
        if "volume" not in out and _CBM_RE.search(cell):
            out["volume"] = cell
            continue
        if "amount" not in out and _number_of(cell):
            out["amount"] = cell
    return out


def _assign_from_text(rest: str) -> dict[str, str]:
    """松散文本兜底：整行里按模式找值，描述取第一个值之前的文本。"""
    out: dict[str, str] = {}
    marks: list[int] = []

    def take(key: str, pattern: re.Pattern[str], value_group: int = 0) -> None:
        m = pattern.search(rest)
        if m and key not in out:
            out[key] = m.group(value_group)
            marks.append(m.start())

    take("hs_code", _HS_RE)
    take("quantity", _QTY_RE)
    take("packages", _PKG_RE)

    kgs = list(_KG_RE.finditer(rest))
    if kgs:
        out["net_weight"] = kgs[0].group(0)
        marks.append(kgs[0].start())
        if len(kgs) >= 2:
            out["gross_weight"] = kgs[1].group(0)
            marks.append(kgs[1].start())

    take("volume", _CBM_RE)

    money = list(_MONEY_RE.finditer(rest))
    if money:
        last = money[-1]
        out["amount"] = last.group(0)
        marks.append(last.start())

    if marks:
        out["description"] = rest[: min(marks)].strip(" ,;|-")
    return out


def _field(spec: FieldSpec, status: str, raw_value: str | None = None, normalized=None,
           unit: str | None = None, score: float | None = None) -> dict:
    return {
        "field_key": spec.key,
        "label": spec.label,
        "raw_text": None,
        "raw_value": raw_value,
        "normalized_value": normalized,
        "unit": unit,
        "confidence": None,  # 正则通道给不出标定可信度，一律 null
        "status": status,
        "page": None,
        "bbox": None,
        "bbox_unit": None,
    }


_NORMALIZERS = {
    "item_code": lambda v: (v.strip().upper() if v else None),
    "description": lambda v: N.normalize_description(v),
    "hs_code": lambda v: N.to_hs_code(v),
    "unit_price": lambda v: N.to_number(v),
    "amount": lambda v: N.to_number(v),
}


# 表头出现顺序（用于把单元格按列对齐）
ITEM_LEVEL_ORDER = [s.key for s in ITEM_LEVEL]


def _row_fields(assigned: dict[str, str], header_keys: set[str], confidence_ok: bool) -> list[dict]:
    fields: list[dict] = []
    for spec in ITEM_LEVEL:
        raw = assigned.get(spec.key)
        if not raw:
            # 表头里有这一列 → 该有没抽到；表头里没有 → 本就不适用
            status = "MISSING_IN_DOC" if spec.key in header_keys else "NOT_IN_DOC"
            fields.append(_field(spec, status=status))
            continue

        if spec.key in {"quantity", "packages", "net_weight", "gross_weight", "volume"}:
            normalized, detected_unit = N.to_measure(raw, spec.key)
        else:
            normalized = _NORMALIZERS[spec.key](raw)
            detected_unit = spec.unit
        if normalized is None:
            fields.append(_field(spec, status="NORMALIZE_FAILED", raw_value=raw[:80]))
            continue

        unit = detected_unit
        if spec.key == "amount":
            unit = None  # 行金额的币种来自票级 currency，不在行内重复
        status = "EXTRACTED" if confidence_ok else "LOW_CONFIDENCE"
        fields.append(_field(spec, status=status, raw_value=raw[:80], normalized=normalized, unit=unit))
    return fields


# --------------------------------------------------------------------------
# 3) 主入口
# --------------------------------------------------------------------------
def _stacked_table(text: str) -> tuple[str, bool]:
    """Restore cell-per-line output only with explicit headers and numbered boundaries."""
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if line.strip().upper().rstrip('.') != 'NO':
            continue
        headers, keys = [], []
        pos = start + 1
        while pos < len(lines):
            cell = lines[pos].strip()
            matches = [key for pattern, key in HEADER_MAP if pattern.fullmatch(cell)]
            if len(matches) != 1:
                break
            headers.append(cell); keys.append(matches[0]); pos += 1
        if len(keys) < 3 or 'description' not in keys or 'quantity' not in keys:
            continue
        # Combined DESCRIPTION / SKU carries both attributes in the same cell.
        combined = any(re.fullmatch(r'DESCRIPTION\s*/\s*SKU', h, re.I) for h in headers)
        if not combined or keys[0] != 'description' or len(set(keys)) != len(keys):
            return text, True
        restored = ['NO.   ITEM NO.   ' + '   '.join(headers)]
        number = 1
        while pos < len(lines) and not TOTAL_LINE.match(lines[pos]):
            if lines[pos].strip() != str(number):
                return text, True
            pos += 1
            description = []
            while pos < len(lines) and not re.fullmatch(r'\d[\d,.]*(?:\s*(?:PCS|SETS|UNITS))?', lines[pos].strip(), re.I):
                description.append(lines[pos].strip()); pos += 1
            desc = ' '.join(description)
            code = re.search(r'\bSKU-[A-Za-z0-9-]+\b', desc)
            if code is None or pos + len(keys) - 1 > len(lines):
                return text, True
            values = lines[pos:pos + len(keys) - 1]
            if not all(v == EMPTY_CELL or re.fullmatch(r'\d[\d,.]*(?:\s*(?:PCS|SETS|UNITS))?', v.strip(), re.I) for v in values):
                return text, True
            for index, key in enumerate(keys[1:]):
                if key in {'gross_weight', 'net_weight'} and 'KG' in headers[index + 1].upper():
                    values[index] += ' KG'
                elif key == 'volume' and headers[index + 1].upper() == 'CBM':
                    values[index] += ' CBM'
            restored.append('   '.join([str(number), code.group(), desc, *values]))
            pos += len(keys) - 1; number += 1
        if number == 1 or pos >= len(lines):
            return text, True
        return '\n'.join(lines[:start] + restored + lines[pos:]), False
    return text, False


def parse_line_items(text: str, page: int | None = None) -> TableResult:
    """把文本拆成 (票级文本, 品名行)。纯函数，不改入参。"""
    text, stacked_failed = _stacked_table(text)
    if stacked_failed:
        return TableResult(doc_text=text, suspected=True)
    doc_text, row_lines, header_order = split_table(text)
    header_keys = set(header_order)
    first_header = next((line for line in text.splitlines() if _looks_like_header(line)), None)
    carton_header = first_header if first_header and any(
        re.fullmatch(r'CARTONS?\.?|CTNS?\.?', cell, re.I) for cell in _cells(first_header)) else None
    if not row_lines:
        return TableResult(doc_text=doc_text)

    # 只要表头存在，行级字段清单就以表头为准
    if not header_keys:
        header_keys = {s.key for s in ITEM_LEVEL}

    line_items: list[dict] = []
    suspected = len(row_lines) > MAX_ROWS
    saw_content = False
    seen_item_nos: set[int] = set()

    for line in row_lines[:MAX_ROWS]:
        if not line.strip():
            continue
        saw_content = True
        m = ROW_START.match(line)
        if not m:
            # 没行首序号：可能是换行的续行，或者这张表根本没有序号列。
            # 有 ≥2 个空格的版面才敢当一行处理。
            parts = _cells(line)
            if not parts:
                suspected = True
                continue
            item_no = len(line_items) + 1
            assigned = _assign_from_cells(parts, header_order)
            reliable = False
            if not header_order or len(parts) != len(header_order):
                suspected = True
            saw_content = True
        else:
            item_no = int(m.group(1))
            parts = _cells(line)
            rest = ROW_START.sub("", line.strip(), count=1)
            if header_order and len(parts) == len(header_order):
                assigned = _assign_from_cells(parts, header_order)
                reliable = True
            else:
                assigned = _assign_from_text(rest)
                reliable = False
                suspected = True

        if not assigned:
            suspected = True
            continue
        # 描述与金额是判断「这行读对了没」的两个关键列
        if not assigned.get("description"):
            suspected = True
        if item_no in seen_item_nos:
            suspected = True
        seen_item_nos.add(item_no)

        row_fields = _row_fields(assigned, header_keys, confidence_ok=reliable)
        if carton_header:
            package = next(field for field in row_fields if field['field_key'] == 'packages')
            if package.get('normalized_value') is not None and package.get('unit') is None:
                package['unit'] = 'CARTON'
        for field in row_fields:
            if field['raw_value'] is not None:
                field['raw_text'] = line.replace(EMPTY_CELL, "").strip()
                if field['field_key'] == 'packages' and carton_header:
                    field['raw_text'] = carton_header + '\n' + field['raw_text']
                field['page'] = page
        line_items.append(
            {
                "item_no": item_no,
                "raw_text": line.replace(EMPTY_CELL, "").strip(),
                "fields": row_fields,
            }
        )

    if saw_content and not line_items:
        suspected = True

    return TableResult(
        line_items=line_items,
        doc_text=doc_text,
        header_keys=header_keys,
        has_table=bool(line_items),
        suspected=suspected,
    )
