"""Local PaddleOCR adapter. Importing this module does not load any models."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from io import BytesIO
from threading import Lock

from .reader import ReadResult
from .rows import HEADER_MAP, _looks_like_header
from ..config import MIN_TEXT_LAYER_CHARS
from ..models import ParseMethod

_ocr = None
_structure = None
_model_lock = Lock()
_run_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-ocr")


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            if any(key in {"rowspan", "colspan"} and value not in {None, "1"} for key, value in attrs):
                raise ValueError("合并单元格无法可靠对应字段列")
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _table_lines(html: str) -> list[str]:
    parser = _TableParser()
    parser.feed(html)
    if len(parser.tables) != 1:
        raise ValueError("未识别出唯一的商品明细表")
    table = parser.tables[0]
    if len(table) < 2 or len({len(row) for row in table}) != 1:
        raise ValueError("商品明细表列数不一致")
    width = len(table[0])
    keep = [i for i in range(width) if any(row[i].strip() for row in table)]
    if not keep or any(not table[0][i].strip() for i in keep):
        raise ValueError("商品明细表表头不完整")
    return ["   ".join(row[i].strip() for i in keep) for row in table]


def _header_key(cell: str) -> str | None:
    keys = {key for pattern, key in HEADER_MAP if pattern.fullmatch(cell.strip().rstrip("."))}
    return next(iter(keys)) if len(keys) == 1 else None


def _table_start(lines: list[str]) -> int | None:
    # 与抽取层共用列名；OCR 表头可能没有句点、序号列，或使用中文。
    for i, line in enumerate(lines):
        if _looks_like_header(line):
            return i
        keys = set()
        for cell in lines[i : i + 12]:
            if cell.strip().upper().rstrip(".") in {"NO", "序号"}:
                continue
            key = _header_key(cell)
            if key is None:
                break
            keys.add(key)
        if len(keys) >= 3:
            return i
    return None


def _replace_table(lines: list[str], table_lines: list[str]) -> str:
    start = _table_start(lines)
    end = next((i for i, line in enumerate(lines) if i > (start or 0) and re.match(r"\s*(?:合计|TOTAL|GRAND TOTAL)\b", line, re.I)), None)
    if start is None or end is None or end <= start:
        raise ValueError("无法确定 OCR 表格在原文中的边界")
    return "\n".join(lines[:start] + table_lines + lines[end:])


def _sequential_packing_table(lines: list[str]) -> list[str]:
    """Guarded fallback for OCR output with one cell per line and no HTML table."""
    start = next((i for i, x in enumerate(lines) if x.upper() == "NO."), None)
    expected = ["NO.", "ITEM NO.", "DESCRIPTION", "QTY", "PACKAGES", "G.W."]
    if start is None or [x.upper() for x in lines[start : start + len(expected)]] != expected:
        raise ValueError("无法可靠还原商品明细表表头")
    pos = start + len(expected)
    rows = ["   ".join(expected)]
    item_no = 1
    while pos < len(lines) and not re.match(r"(?:合计|TOTAL)\b", lines[pos], re.I):
        if lines[pos] != str(item_no) or pos + 5 >= len(lines):
            raise ValueError("商品明细表行边界或序号不可靠")
        code, desc, qty = lines[pos + 1 : pos + 4]
        if not re.fullmatch(r"[A-Z]{1,6}[-/]?\w{2,12}", code, re.I) or not desc or not re.fullmatch(r"\d[\d,.]*\s*(?:PCS|PIECES|SETS|UNITS)", qty, re.I):
            raise ValueError("商品明细表货号、品名或数量无法确认")
        package = lines[pos + 4]
        next_pos = pos + 5
        if re.fullmatch(r"\d[\d,.]*", package) and next_pos < len(lines) and re.fullmatch(r"CTNS?|CARTONS?|PACKAGES?", lines[next_pos], re.I):
            package += " " + lines[next_pos]
            next_pos += 1
        if not re.fullmatch(r"\d[\d,.]*\s*(?:CTNS?|CARTONS?|PACKAGES?)", package, re.I) or next_pos >= len(lines):
            raise ValueError("商品明细表件数无法确认")
        weight = lines[next_pos]
        if not re.fullmatch(r"\d[\d,.]*(?:\s*KGS?)?", weight, re.I):
            raise ValueError("商品明细表毛重无法确认")
        rows.append("   ".join([str(item_no), code, desc, qty, package, weight]))
        pos = next_pos + 1
        item_no += 1
    if item_no < 2 or pos >= len(lines):
        raise ValueError("商品明细表合计边界缺失")
    return rows


def _correct_zero_confusion(value: str) -> str:
    """Only replace O inside a digit-plus-unit token, e.g. 35OML -> 350ML."""
    return re.sub(
        r"(?<![A-Z0-9])(\d[0-9O]*)(ML|KG|CM|MM|G|L)(?![A-Z0-9])",
        lambda match: match.group(1).replace("O", "0") + match.group(2),
        value.upper(),
    )


def _check_descriptions(table_lines: list[str], ocr_lines: list[str]) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Cross-check two OCR paths; resolve only unambiguous zero/O unit tokens."""
    header = table_lines[0].split("   ")
    code_at = next((i for i, h in enumerate(header) if _header_key(h) == "item_code"), None)
    desc_at = next((i for i, h in enumerate(header) if _header_key(h) == "description"), None)
    if code_at is None or desc_at is None:
        raise ValueError("商品明细表缺少可交叉核验的货号或品名列")
    uncertain: list[str] = []
    corrections: list[dict[str, str]] = []
    out = [table_lines[0]]
    for row in table_lines[1:]:
        cells = row.split("   ")
        code = cells[code_at]
        where = next((i for i, text in enumerate(ocr_lines[:-1]) if text.strip().upper() == code.upper()), None)
        if where is None:
            uncertain.append(code)
        else:
            ordinary = ocr_lines[where + 1].strip()
            structured = cells[desc_at]
            compact = lambda value: re.sub(r"\s+", "", value).casefold()
            if compact(ordinary) != compact(structured):
                valid_measure = r"(?<![A-Z0-9])\d+(?:\.\d+)?(?:ML|KG|CM|MM|G|L)(?![A-Z0-9])"
                if re.search(valid_measure, ordinary.upper()) and compact(_correct_zero_confusion(structured)) == compact(ordinary):
                    cells[desc_at] = ordinary
                    corrections.append({"item_code": code, "original": structured, "corrected": ordinary})
                elif re.search(valid_measure, structured.upper()) and compact(_correct_zero_confusion(ordinary)) == compact(structured):
                    corrections.append({"item_code": code, "original": ordinary, "corrected": structured})
                else:
                    uncertain.append(code)
            else:
                cells[desc_at] = ordinary
        out.append("   ".join(cells))
    return out, uncertain, corrections


def _get_ocr():
    global _ocr
    with _model_lock:
        if _ocr is None:
            from paddleocr import PaddleOCR
            _ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
    return _ocr


def _get_structure():
    global _structure
    with _model_lock:
        if _structure is None:
            from paddleocr import PPStructureV3
            _structure = PPStructureV3(use_doc_orientation_classify=False, use_doc_unwarping=False, use_formula_recognition=False, use_seal_recognition=False)
    return _structure


def read_image(data: bytes) -> ReadResult:
    # Paddle 推理器需在同一线程创建和复用；互斥锁无法保证跨任务线程的稳定性。
    return _run_executor.submit(_recognize_image, data).result()


def _recognize_image(data: bytes) -> ReadResult:
    """Recognize one image; reject uncertain table reconstruction."""
    try:
        from PIL import Image
        import numpy as np
        source = Image.open(BytesIO(data))
        if getattr(source, "n_frames", 1) != 1:
            raise ValueError("多帧图片尚不支持逐页识别")
        image = np.asarray(source.convert("RGB"))
        results = list(_get_ocr().predict(input=image))
        if len(results) != 1:
            raise ValueError("OCR 未返回单页结果")
        lines = [str(x).strip() for x in results[0].json["res"]["rec_texts"] if str(x).strip()]
        uncertain: list[str] = []
        corrections: list[dict[str, str]] = []
        if _table_start(lines) is not None:
            structure = list(_get_structure().predict(input=image))
            if len(structure) != 1:
                raise ValueError("表格识别未返回单页结果")
            markdown = structure[0].markdown["markdown_texts"]
            # 交给解析器检查整页，不能截出第一张表后静默丢弃其他表格。
            lines_text = _table_lines(markdown) if re.search(r"<table\b", markdown, re.I) else _sequential_packing_table(lines)
            lines_text, uncertain, corrections = _check_descriptions(lines_text, lines)
            text = _replace_table(lines, lines_text)
        else:
            text = "\n".join(lines)
        if len(text.strip()) < MIN_TEXT_LAYER_CHARS:
            raise ValueError("OCR 返回文字过少")
        return ReadResult(text=text, page_count=1, parse_method=ParseMethod.OCR, uncertain_item_codes=uncertain, ocr_corrections=corrections)
    except Exception as exc:  # noqa: BLE001
        return ReadResult(error_message=f"PaddleOCR 识别失败：{exc}", page_count=1, failed=True)
