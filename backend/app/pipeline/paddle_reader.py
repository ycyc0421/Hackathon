"""Local PaddleOCR adapter. Importing this module does not load any models."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from io import BytesIO
from threading import Lock

from .reader import ReadResult
from .rows import EMPTY_CELL, HEADER_MAP, _looks_like_header
from ..config import MIN_TEXT_LAYER_CHARS
from ..models import ParseMethod

_ocr = None
_structure = None
_model_lock = Lock()
_run_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-ocr")


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table_spans = []
        self._table = None
        self._row = None
        self._cell = None
        self._span = (1, 1)
        self._carry = {}

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self._table is not None:
                raise ValueError("嵌套表格无法可靠对应字段列")
            self._table, self._carry, self._spans = [], {}, []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            attributes = dict(attrs)
            try:
                self._span = (int(attributes.get('rowspan', '1')), int(attributes.get('colspan', '1')))
            except (TypeError, ValueError):
                raise ValueError("合并单元格跨度无效")
            if any(n < 1 or n > 200 for n in self._span):
                raise ValueError("合并单元格跨度超限")
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._cell is not None:
            self._row.append(("".join(self._cell).strip(), *self._span))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            row, following, col = [], {}, 0
            def carried():
                nonlocal col
                while col in self._carry:
                    value, remaining = self._carry[col]
                    row.append(value)
                    if remaining > 1:
                        following[col] = (value, remaining - 1)
                    col += 1
            carried()
            for value, rowspan, colspan in self._row:
                if rowspan > 1 or colspan > 1:
                    self._spans.append((len(self._table), col, value, rowspan, colspan))
                for offset in range(colspan):
                    if col in self._carry:
                        raise ValueError("合并单元格重叠")
                    # Spanning a data value over different columns is ambiguous.
                    cell = value if offset == 0 else ''
                    row.append(cell)
                    if rowspan > 1:
                        following[col] = (cell, rowspan - 1)
                    col += 1
                carried()
            if self._carry.keys() - set(range(col)):
                raise ValueError("合并单元格存在列间空洞")
            self._table.append(row)
            self._carry, self._row = following, None
        elif tag == "table" and self._table is not None:
            if self._carry:
                raise ValueError("合并单元格超出表格范围")
            self.tables.append(self._table)
            self.table_spans.append(self._spans)
            self._table = None


def _table_lines(html: str) -> list[str]:
    import re
    parser = _TableParser()
    parser.feed(html)
    candidates = []
    for table, spans in zip(parser.tables, parser.table_spans):
        for index, row in enumerate(table):
            keys = {_header_key(cell) for cell in row} - {None}
            if len(keys) >= 2 and keys & {'item_code', 'description'} and keys & {'quantity', 'amount', 'packages'}:
                candidates.append((table[index:], spans, index))
                break
    if len(candidates) != 1:
        raise ValueError("未识别出唯一的商品明细表")
    table, spans, header_at = candidates[0]
    original_headers = table[0][:]
    is_total = lambda value: bool(re.fullmatch(r'TOTAL(?:\s+(?:AMOUNT|QUANTITY|PACKAGES|WEIGHT))?(?:\s*\([A-Z]{3}\))?', value.strip(), re.I))
    total_at = next((index for index, row in enumerate(table[1:], 1) if row and is_total(row[0])), len(table))
    footers = table[total_at:]
    if any(not row or not is_total(row[0]) for row in footers):
        raise ValueError('合计行之后仍有无法归属的商品数据')
    for row, col, value, rowspan, colspan in spans:
        if row <= header_at or not value.strip():
            continue
        # An explicit TOTAL label may span columns; numeric data never may.
        if row - header_at >= total_at and col == 0 and rowspan == 1 and is_total(value):
            continue
        # A value spanning exactly the same description columns as the header
        # has a single owner. Other populated data spans remain ambiguous.
        description_span = any(
            hrow == header_at and hcol == col and hcolspan == colspan
            and _header_key(hvalue) == 'description'
            for hrow, hcol, hvalue, _, hcolspan in spans
        )
        if rowspan > 1 or not description_span:
            raise ValueError("商品数据合并单元格的归属不明确，不能重复分配数值")
    table = table[:total_at]
    if len(table) < 2 or len({len(row) for row in table}) != 1:
        raise ValueError("商品明细表列数不一致")
    keep = [i for i in range(len(table[0])) if any(row[i].strip() for row in table)]
    if not keep or any(not table[0][i].strip() for i in keep):
        raise ValueError("商品明细表表头不完整")
    table = [[row[i] for i in keep] for row in table]
    keep = list(range(len(table[0])))
    # Extract an explicitly labelled SKU from a combined description cell.
    combined = next((i for i, cell in enumerate(table[0]) if cell.upper().replace(' ', '') == 'DESCRIPTION/SKU'), None)
    if combined is not None:
        expanded = [table[0][:combined] + ['ITEM NO.', 'DESCRIPTION'] + table[0][combined + 1:]]
        for row in table[1:]:
            match = re.search(r'\bSKU-[A-Za-z0-9-]+\b', row[combined])
            if match is None:
                raise ValueError('商品明细表缺少明确货号')
            expanded.append(row[:combined] + [match.group(), row[combined]] + row[combined + 1:])
        table = expanded
        keep = list(range(len(table[0])))
    elif not any(_header_key(cell) == 'item_code' for cell in table[0]):
        description_at = next((i for i, cell in enumerate(table[0]) if _header_key(cell) == 'description'), None)
        if description_at is not None and all(
            re.search(r'\bSKU\s*:\s*([A-Z0-9][A-Z0-9-]+)\b', row[description_at], re.I)
            for row in table[1:] if any(cell.strip() for cell in row)
        ):
            expanded = [table[0][:description_at] + ['ITEM NO.'] + table[0][description_at:]]
            for row in table[1:]:
                if not any(cell.strip() for cell in row):
                    continue
                match = re.search(r'\bSKU\s*:\s*([A-Z0-9][A-Z0-9-]+)\b', row[description_at], re.I)
                expanded.append(row[:description_at] + [match.group(1)] +
                                [row[description_at][:match.start()].strip()] + row[description_at + 1:])
            table = expanded
            keep = list(range(len(table[0])))
    # A blank data cell remains missing; never shift later columns left.
    lines = ["   ".join(' '.join(row[i].split()) or EMPTY_CELL for i in keep) for row in table]
    for row in footers:
        if re.search(r'AMOUNT', row[0], re.I):
            lines.append('   '.join([row[0]] + [cell for cell in row[1:] if cell.strip() and cell != row[0]]))
        else:
            for column, cell in enumerate(row[1:], 1):
                if cell.strip() and cell != row[0] and column < len(original_headers):
                    # Keep each total's original column meaning. Bare TOTAL 500
                    # must never turn packing quantity into invoice money.
                    lines.append(f'TOTAL {original_headers[column]}: {cell}')
    return lines


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


def _sequential_shirt_table(lines: list[str]) -> list[str]:
    """Guarded restoration for the numbered one-item invoice/packing layout."""
    upper = [line.upper() for line in lines]
    invoice = ['NO.', 'DESCRIPTION OF GOODS', 'HS CODE', 'QUANTITY', 'UNIT PRICE', 'AMOUNT (USD)']
    packing = ['NO.', 'DESCRIPTION OF GOODS', 'SKU', 'QTY', 'PKGS', 'NET KG', 'GROSS KG', 'CBM']
    for headers in (invoice, packing):
        start = next((i for i in range(len(lines) - len(headers))
                      if upper[i:i + len(headers)] == headers), None)
        if start is None:
            continue
        pos = start + len(headers)
        if pos >= len(lines) or lines[pos] != '1':
            raise ValueError('商品表序号不可靠')
        if headers is invoice:
            if pos + 7 >= len(lines):
                raise ValueError('发票商品行不完整')
            desc, hs, qty, price, amount, sku_line = lines[pos + 1:pos + 7]
            sku = re.fullmatch(r'SKU\s*:\s*([A-Z0-9][A-Z0-9-]+)', sku_line, re.I)
            if (not sku or not re.fullmatch(r'\d{4}\.\d{2}(?:\.\d{2})?', hs)
                    or not re.fullmatch(r'\d[\d,]*\s*PCS', qty, re.I)
                    or not re.fullmatch(r'\$?\d[\d,]*\.\d{2}', price)
                    or not re.fullmatch(r'\$?\d[\d,]*\.\d{2}', amount)
                    or not upper[pos + 7].startswith('TOTAL AMOUNT')):
                raise ValueError('发票商品行列归属不可靠')
            return ['NO.   ITEM NO.   ' + '   '.join(headers[1:]),
                    '   '.join(['1', sku.group(1), desc, hs, qty, price, amount])]
        if pos + 10 >= len(lines):
            raise ValueError('装箱单商品行不完整')
        desc, sku, qty, packages, net, gross, volume, continuation = lines[pos + 1:pos + 9]
        if (not re.fullmatch(r'[A-Z]{1,6}-\d{2,8}', sku, re.I)
                or not re.fullmatch(r'\d[\d,]*\s*PCS', qty, re.I)
                or not re.fullmatch(r'\d[\d,]*', packages)
                or any(not re.fullmatch(r'\d[\d,]*\.\d{2,3}', v) for v in (net, gross, volume))
                or upper[pos + 9] != 'TOTAL'):
            raise ValueError('装箱单商品行列归属不可靠')
        return ['   '.join(headers),
                '   '.join(['1', (desc + ' ' + continuation).strip(), sku, qty, packages,
                            net + ' KG', gross + ' KG', volume + ' CBM'])]
    raise ValueError('未找到受支持的连续单元格商品表')


def _correct_zero_confusion(value: str) -> str:
    """Only replace O inside a digit-plus-unit token, e.g. 35OML -> 350ML."""
    return re.sub(
        r"(?<![A-Z0-9])(\d[0-9O]*)(ML|KG|CM|MM|G|L)(?![A-Z0-9])",
        lambda match: match.group(1).replace("O", "0") + match.group(2),
        value.upper(),
    )


def _reconcile_document_no(lines: list[str], markdown: str) -> list[str]:
    """Resolve a CI/Cl OCR ambiguity only when the second OCR path agrees."""
    if not any(line.strip().upper() == 'COMMERCIAL INVOICE' for line in lines):
        return lines
    structured = re.search(r'Document\s+No\.?\s*:\s*(CI-\d{8}-\d{8})(?=Date:|\s|<|$)', markdown, re.I)
    if structured is None:
        return lines
    number = structured.group(1).upper()
    out = list(lines)
    for index, line in enumerate(out):
        ordinary = re.fullmatch(r'(Document\s+No\.?\s*:\s*)(Cl-[A-Z0-9-]+)', line.strip(), re.I)
        if ordinary and ordinary.group(2).upper().replace('CL-', 'CI-', 1) == number:
            out[index] = f'{ordinary.group(1)}{number} [OCR raw: {ordinary.group(2)}]'
            break
    return out


def _structured_parties(lines: list[str], markdown: str) -> list[str]:
    """Map companies through labelled HTML cells, verified against ordinary OCR."""
    parser = _TableParser()
    parser.feed(markdown)
    compact = lambda value: re.sub(r'[^a-z0-9]', '', value.casefold())
    mapped = {}
    labels = {'SELLER': r'(?:SELLER|SHIPPER)\s*/\s*EXPORTER',
              'BUYER': r'(?:BUYER|CONSIGNEE)\s*/\s*IMPORTER'}
    for table in parser.tables:
        for index, row in enumerate(table):
            for column, cell in enumerate(row):
                for role, pattern in labels.items():
                    match = re.match(pattern + r'\s*[:：]?\s*', cell, re.I)
                    if not match:
                        continue
                    value = cell[match.end():].strip()
                    if not value and index + 1 < len(table) and column < len(table[index + 1]):
                        value = table[index + 1][column].strip()
                    company = re.match(r'.+?(?:Co\.?\s*,?\s*Ltd\.?|Inc\.?|Limited|LLC)(?=\s|$)', value, re.I)
                    if not company:
                        continue
                    expected = compact(company.group())
                    candidates = [line for line in lines if compact(line) == expected]
                    if len(candidates) == 1:
                        mapped.setdefault(role, set()).add(candidates[0])
    if set(mapped) == {'SELLER', 'BUYER'} and all(len(values) == 1 for values in mapped.values()):
        seller, buyer = next(iter(mapped['SELLER'])), next(iter(mapped['BUYER']))
        if compact(seller) != compact(buyer):
            return [f'SELLER: {seller}', f'BUYER: {buyer}'] + lines
    return lines


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
        where = next((i for i, text in enumerate(ocr_lines)
                      if text.strip().upper() == code.upper() or
                      re.fullmatch(r'SKU\s*:\s*' + re.escape(code), text.strip(), re.I)), None)
        if where is None:
            uncertain.append(code)
        else:
            structured = cells[desc_at]
            compact = lambda value: re.sub(r"\s+", "", value).casefold()
            # Ordinary OCR may read a printed SKU below its description.
            # Only accept a nearby line that agrees exactly, or through the
            # narrowly allowed O/0 measure correction.
            candidates = ocr_lines[max(0, where - 8):where] + ocr_lines[where + 1:where + 2]
            matches = [candidate.strip() for candidate in candidates if
                       compact(candidate) == compact(structured) or
                       compact(_correct_zero_confusion(candidate)) == compact(structured) or
                       compact(candidate) == compact(_correct_zero_confusion(structured))]
            if len(matches) != 1:
                uncertain.append(code)
                out.append("   ".join(cells))
                continue
            ordinary = matches[0]
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
            _ocr = PaddleOCR(cpu_threads=4, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
    return _ocr


def _get_structure():
    global _structure
    with _model_lock:
        if _structure is None:
            from paddleocr import PPStructureV3
            _structure = PPStructureV3(cpu_threads=4, use_doc_orientation_classify=False, use_doc_unwarping=False, use_formula_recognition=False, use_seal_recognition=False)
    return _structure


def read_image(data: bytes) -> ReadResult:
    # Paddle 推理器需在同一线程创建和复用；互斥锁无法保证跨任务线程的稳定性。
    from ..config import PADDLE_OCR_ENGINE
    if PADDLE_OCR_ENGINE == 'vl':
        from .paddle_vl_reader import recognize_image
        return _run_executor.submit(recognize_image, data).result()
    if PADDLE_OCR_ENGINE == 'legacy':
        return _run_executor.submit(_recognize_image, data).result()
    return ReadResult(failed=True, error_message='PADDLE_OCR_ENGINE 仅支持 vl 或 legacy')


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
            lines = _reconcile_document_no(lines, markdown)
            lines = _structured_parties(lines, markdown)
            # 交给解析器检查整页，不能截出第一张表后静默丢弃其他表格。
            try:
                lines_text = _table_lines(markdown) if re.search(r"<table\b", markdown, re.I) else _sequential_packing_table(lines)
                lines_text, uncertain, corrections = _check_descriptions(lines_text, lines)
            except ValueError as original_error:
                # Keep this fallback narrow: exact headers, numbered row,
                # typed numeric cells and an explicit total boundary.
                if len(re.findall(r"<table\b", markdown, re.I)) != 1:
                    raise original_error
                try:
                    lines_text = _sequential_shirt_table(lines)
                except ValueError:
                    raise original_error
                # The fallback restores layout; it does not establish an
                # independent agreement on the product description.
                code_column = next(i for i, cell in enumerate(lines_text[0].split('   '))
                                   if _header_key(cell) == 'item_code')
                uncertain = [row.split('   ')[code_column] for row in lines_text[1:]]
            text = _replace_table(lines, lines_text)
        else:
            text = "\n".join(lines)
        if len(text.strip()) < MIN_TEXT_LAYER_CHARS:
            raise ValueError("OCR 返回文字过少")
        return ReadResult(text=text, page_count=1, parse_method=ParseMethod.OCR, uncertain_item_codes=uncertain, ocr_corrections=corrections)
    except Exception as exc:  # noqa: BLE001
        return ReadResult(error_message=f"PaddleOCR 识别失败：{exc}", page_count=1, failed=True)
