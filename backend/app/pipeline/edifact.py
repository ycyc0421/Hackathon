"""Bounded INVOIC D96A adapter; independent of PDF/OCR and project JSON.

Only one enveloped message and selected invoice segments are supported. Unknown
scope-changing segments fail closed. Evidence is the original segment, never a
reconstructed JSON document or a fabricated PDF page.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re

from ..doc_profile import profile_of
from ..schema_fields import BY_KEY, CORE_COMPARABLE, ITEM_LEVEL
from .extract import NORMALIZERS, _field, _norm_text


class EdifactUnsupported(ValueError):
    """A valid-looking message is outside the deliberately small profile."""


@dataclass
class _Segment:
    tag: str
    elements: list[list[str]]
    raw: str

    def component(self, element, component=0):
        values = self.elements[element] if element < len(self.elements) else []
        return values[component] if component < len(values) else ''


_ALLOWED_TAGS = {'UNB', 'UNH', 'BGM', 'DTM', 'FTX', 'RFF', 'NAD', 'CUX',
                 'PAC', 'MEA', 'LIN', 'PIA', 'IMD', 'QTY', 'MOA', 'PRI',
                 'UNS', 'CNT', 'UNT', 'UNZ'}
_UNITS = {'quantity': {'PCE': 'PCS', 'PCS': 'PCS'},
          'packages': {'CT': 'CARTON', 'CTN': 'CARTON'},
          'net_weight': {'KGM': 'KGS'}, 'gross_weight': {'KGM': 'KGS'},
          'volume': {'MTQ': 'CBM'}}


def _segments(data):
    if len(data) > 1024 * 1024:
        raise ValueError('EDI 文件超过 1 MiB')
    try:
        text = data.decode('utf-8-sig').strip(' \r\n\t')
    except UnicodeDecodeError:
        raise ValueError('EDI 不是有效的 UTF-8 文本') from None
    if text.startswith('ISA'):
        raise EdifactUnsupported('当前 EDI 仅支持单个 INVOIC D96A 报文')
    component, element, decimal, release, reserved, end = ':', '+', '.', '?', ' ', "'"
    if text.startswith('UNA'):
        if len(text) < 9:
            raise ValueError('EDI 服务字符声明不完整')
        component, element, decimal, release, reserved, end = text[3:9]
        text = text[9:]
        if (decimal not in '.,' or reserved != ' ' or
                len({component, element, decimal, release, end}) != 5 or
                any(not 33 <= ord(c) <= 126 or c.isalnum() for c in (component, element, release, end))):
            raise EdifactUnsupported('当前 EDI 服务字符或语法版本不受支持')
    segments, elements, components, value = [], [], [], []
    start, escaped = None, False
    for index, char in enumerate(text):
        if start is None:
            if char in ' \r\n\t':
                continue
            start = index
        if escaped:
            if char not in {component, element, decimal, release, reserved, end}:
                raise ValueError('EDI release 转义无效')
            value.append(char)
            escaped = False
        elif char == release:
            escaped = True
        elif char in (component, element, end):
            components.append(''.join(value))
            value = []
            if char in (element, end):
                elements.append(components)
                components = []
            if char == end:
                if len(elements[0]) != 1 or not re.fullmatch(r'[A-Z][A-Z0-9]{2}', elements[0][0]):
                    raise ValueError('EDI 段标识无效')
                raw = text[start:index + 1]
                if len(raw) > 8192 or len(segments) >= 10000:
                    raise ValueError('EDI 段或段数超过限制')
                segments.append(_Segment(elements[0][0], elements[1:], raw))
                elements, start = [], None
        else:
            if (ord(char) < 32 and char not in '\r\n\t') or ord(char) == 127:
                raise ValueError('EDI 文本含无效控制字符')
            value.append(char)
    if escaped or start is not None or not segments:
        raise ValueError('EDI 报文截断或段结束符缺失')
    return segments, decimal


def _integer(value):
    if not re.fullmatch(r'[0-9]{1,9}', value):
        raise ValueError('EDI 计数或引用结构无效')
    return int(value)


def _envelope(segments):
    tags = [s.tag for s in segments]
    if tags.count('UNH') > 1:
        raise EdifactUnsupported('当前 EDI 仅支持单个 INVOIC D96A 报文')
    if tags.count('UNH') != 1:
        raise ValueError('EDI 信封或报文头不完整')
    head = segments[tags.index('UNH')]
    if (tags[0] != 'UNB' or tags[-1] != 'UNZ' or
            any(tags.count(tag) != 1 for tag in ('UNB', 'UNZ', 'UNT')) or
            tags.index('UNH') != 1 or tags.index('UNT') != len(tags) - 2):
        raise ValueError('EDI 信封或报文尾不完整')
    unb, unz, unt = segments[0], segments[-1], segments[-2]
    if (unb.component(0) not in {'UNOA', 'UNOB', 'UNOC'} or unb.component(0, 1) != '3'
            or len(unb.elements[0]) != 2):
        raise EdifactUnsupported('当前 EDI 服务字符或语法版本不受支持')
    if (not unb.component(1) or not unb.component(2) or
            not re.fullmatch(r'[0-9]{6}', unb.component(3)) or
            not re.fullmatch(r'[0-9]{4}', unb.component(3, 1)) or
            len(head.elements) != 2 or len(head.elements[0]) != 1 or
            len(unt.elements) != 2 or len(unz.elements) != 2 or
            any(len(e) != 1 for s in (unt, unz) for e in s.elements)):
        raise ValueError('EDI 信封结构无效')
    if not head.component(0) or unt.component(1) != head.component(0):
        raise ValueError('EDI UNT 报文引用不一致')
    if _integer(unt.component(0)) != len(segments) - 2:
        raise ValueError('EDI UNT 段数不一致')
    if not unb.component(4) or unz.component(1) != unb.component(4):
        raise ValueError('EDI UNZ 交换引用不一致')
    if _integer(unz.component(0)) != 1:
        raise ValueError('EDI UNZ 报文数不一致')
    if head.elements[1:] != [['INVOIC', 'D', '96A', 'UN']]:
        raise EdifactUnsupported('当前 EDI 仅支持单个 INVOIC D96A 报文')
    if any(tag not in _ALLOWED_TAGS for tag in tags):
        raise EdifactUnsupported('EDI 含当前未支持的业务段')


def _numeric(raw, decimal):
    # UNA owns the decimal sign: no thousands guessing or substring extraction.
    if not re.fullmatch(r'[+-]?[0-9]+(?:' + re.escape(decimal) + r'[0-9]+)?', raw):
        return None
    try:
        number = Decimal(raw.replace(decimal, '.'))
        if not number.is_finite() or abs(number) > Decimal('1e15'):
            return None
        value = int(number) if number == number.to_integral_value() else float(number)
        return value if math.isfinite(value) else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _put(target, key, raw, segment, *, numeric=False, source_unit=None, decimal='.'):
    if not raw or len(raw) > 2000:
        raise ValueError('EDI 必需值为空或超过限制')
    unit = None
    if numeric:
        value = _numeric(raw, decimal)
        if key in _UNITS:
            unit = _UNITS[key].get(source_unit)
            if key != 'packages' and unit is None:
                value = None
            if value is not None and (value < 0 or (key == 'packages' and not isinstance(value, int))):
                value = None
        else:
            unit = source_unit
    elif key == 'hs_code':
        value = raw if re.fullmatch(r'[0-9]{6,12}', raw) else None
    elif key == 'destination_country':
        value = NORMALIZERS[key](raw)[0] if re.fullmatch(r'[A-Za-z]{2}', raw) else None
    else:
        value = NORMALIZERS.get(key, _norm_text)(raw)[0]
    result = _field(BY_KEY[key], 'EXTRACTED' if value is not None else 'NORMALIZE_FAILED',
                    raw_text=segment.raw, raw_value=raw, normalized_value=value, unit=unit, page=None)
    if key in target and (target[key]['normalized_value'], target[key]['raw_value'], target[key]['unit']) != (value, raw, unit):
        raise ValueError('EDI 同一字段重复且值不一致')
    target.setdefault(key, result)


def parse_edifact(data: bytes) -> dict:
    segments, decimal = _segments(data)
    _envelope(segments)
    document, rows, current, summary = {}, [], None, False
    row_numbers, item_count, bgm_count = set(), None, 0
    for segment in segments[2:-2]:
        tag, c = segment.tag, segment.component
        if tag == 'BGM':
            bgm_count += 1
            if bgm_count != 1 or rows or c(0) != '380' or c(2) not in ('9', '7'):
                raise EdifactUnsupported('EDI 发票种类或段归属不受支持')
            if len(segment.elements) != 3 or any(len(e) != 1 for e in segment.elements):
                raise EdifactUnsupported('EDI 发票段格式不受支持')
            _put(document, 'document_no', c(1), segment)
            _put(document, 'invoice_no', c(1), segment)
        elif tag == 'LIN':
            if summary or len(rows) >= 200:
                raise ValueError('EDI 商品行顺序或行数无效')
            number = _integer(c(0))
            if number < 1 or number in row_numbers:
                raise ValueError('EDI 商品行号重复或无效')
            if (len(segment.elements) != 3 or len(segment.elements[0]) != 1 or
                    c(1) or c(2, 1) != 'SA' or any(segment.elements[2][2:])):
                raise EdifactUnsupported('EDI 商品标识或码表不受支持')
            row_numbers.add(number)
            current = {'item_no': number, 'fields': {}, 'segments': [segment.raw]}
            rows.append(current)
            _put(current['fields'], 'item_code', c(2), segment)
        elif tag == 'UNS':
            if segment.elements != [['S']] or summary:
                raise ValueError('EDI 汇总段顺序无效')
            summary, current = True, None
        else:
            if current is not None:
                current['segments'].append(segment.raw)
            target = current['fields'] if current is not None else document
            if tag == 'CUX':
                if rows or summary or c(0) != '2' or c(0, 2) != '4' or any(segment.elements[0][3:]) or any(any(e) for e in segment.elements[1:]):
                    raise EdifactUnsupported('EDI 币种限定或段归属不受支持')
                if not re.fullmatch(r'[A-Za-z]{3}', c(0, 1)):
                    raise ValueError('EDI 币种代码无效')
                _put(document, 'currency', c(0, 1), segment)
            elif tag == 'NAD':
                if rows or summary:
                    raise EdifactUnsupported('EDI 主体段归属不受支持')
                key = {'CZ': 'shipper', 'CN': 'consignee'}.get(c(0))
                if key and (len(segment.elements[0]) != 1 or
                            (len(segment.elements) > 8 and len(segment.elements[8]) != 1)):
                    raise EdifactUnsupported('EDI 主体或国家格式不受支持')
                if key and c(3):
                    if len(segment.elements) > 9 or any(segment.elements[3][5:]):
                        raise EdifactUnsupported('EDI 主体名称格式不受支持')
                    _put(document, key, ' '.join(segment.elements[3][:5]).strip(), segment)
                if key == 'consignee' and c(8):
                    _put(document, 'destination_country', c(8), segment)
            elif tag == 'DTM' and c(0) == '11':
                if rows or summary or len(segment.elements) != 1 or len(segment.elements[0]) != 3 or c(0, 2) != '102':
                    raise EdifactUnsupported('EDI 日期格式或段归属不受支持')
                _put(document, 'shipment_date', c(0, 1), segment)
            elif tag == 'PIA':
                if current is None:
                    raise EdifactUnsupported('EDI 商品字段段归属不受支持')
                if len(segment.elements[0]) != 1:
                    raise EdifactUnsupported('EDI 商品标识或码表不受支持')
                for element in segment.elements[1:]:
                    if len(element) > 1 and element[1] == 'HS':
                        if c(0) != '1' or any(element[2:]):
                            raise EdifactUnsupported('EDI 商品标识或码表不受支持')
                        _put(target, 'hs_code', element[0], segment)
            elif tag == 'IMD' and c(0) == 'F':
                if (current is None or len(segment.elements) != 3 or len(segment.elements[0]) != 1 or c(1) or
                        any(segment.elements[2][:3]) or any(segment.elements[2][5:])):
                    raise EdifactUnsupported('EDI 商品描述格式或段归属不受支持')
                _put(target, 'description', ' '.join(segment.elements[2][3:5]).strip(), segment)
            elif tag == 'QTY' and c(0) == '47':
                if current is None or len(segment.elements) != 1 or any(segment.elements[0][3:]):
                    raise EdifactUnsupported('EDI 商品数量段归属不受支持')
                _put(target, 'quantity', c(0, 1), segment, numeric=True, source_unit=c(0, 2), decimal=decimal)
            elif tag == 'PAC':
                if (summary or len(segment.elements) != 3 or len(segment.elements[0]) != 1 or
                        any(segment.elements[1]) or any(segment.elements[2][1:])):
                    raise EdifactUnsupported('EDI 包装格式或段归属不受支持')
                _put(target, 'packages', c(0), segment, numeric=True, source_unit=c(2), decimal=decimal)
            elif tag == 'MEA':
                keys = {'AAD': 'gross_weight', 'AAC': 'net_weight', 'AAW': 'volume'} if current is None else {'AAE': 'gross_weight', 'AAL': 'net_weight', 'AAW': 'volume'}
                key = keys.get(c(1))
                if key:
                    if len(segment.elements) <= 2:
                        raise ValueError('EDI 重量体积字段不完整')
                    if summary or len(segment.elements) != 3 or c(0) != 'AAE' or any(segment.elements[1][1:]) or any(segment.elements[2][2:]):
                        raise EdifactUnsupported('EDI 重量体积格式或段归属不受支持')
                    _put(target, key, c(2, 1), segment, numeric=True, source_unit=c(2), decimal=decimal)
            elif tag == 'MOA' and c(0) in ('77', '203'):
                key = 'total_amount' if c(0) == '77' else 'amount'
                if len(segment.elements) != 1 or any(segment.elements[0][2:]) or (key == 'amount') != (current is not None):
                    raise EdifactUnsupported('EDI 金额币种或段归属不受支持')
                _put(target, key, c(0, 1), segment, numeric=True, decimal=decimal)
            elif tag == 'PRI' and c(0) == 'AAA':
                if current is None or len(segment.elements) != 1 or c(0, 2) or c(0, 3) or c(0, 4) != '1' or c(0, 5) not in ('PCE', 'PCS') or any(segment.elements[0][6:]):
                    raise EdifactUnsupported('EDI 单价基数或单位不受支持')
                _put(target, 'unit_price', c(0, 1), segment, numeric=True, decimal=decimal)
            elif tag == 'CNT' and c(0) == '2':
                if current is not None or item_count is not None or len(segment.elements) != 1 or len(segment.elements[0]) != 2:
                    raise ValueError('EDI 商品计数段归属无效')
                item_count = _integer(c(0, 1))
    if bgm_count != 1 or not rows or not summary:
        raise ValueError('EDI 发票正文或商品行不完整')
    if item_count is not None and item_count != len(rows):
        raise ValueError('EDI CNT 商品行数不一致')
    currency = document.get('currency', {}).get('normalized_value')
    for target in [document] + [r['fields'] for r in rows]:
        for key in ('amount', 'unit_price', 'total_amount'):
            if key in target:
                target[key]['unit'] = currency
    row_keys = {key for row in rows for key in row['fields']}
    profile = profile_of('COMMERCIAL_INVOICE') or set()
    for spec in CORE_COMPARABLE:
        if spec.key not in document:
            required = spec.key in profile and spec.key not in row_keys
            document[spec.key] = _field(spec, 'MISSING_IN_DOC' if required else 'NOT_IN_DOC', page=None)
    lines = []
    for row in rows:
        for spec in ITEM_LEVEL:
            if spec.key not in row['fields']:
                row['fields'][spec.key] = _field(spec, 'MISSING_IN_DOC' if spec.key in profile else 'NOT_IN_DOC', page=None)
        lines.append({'item_no': row['item_no'], 'raw_text': '\n'.join(row['segments']), 'fields': list(row['fields'].values())})
    return {'doc_type': 'COMMERCIAL_INVOICE', 'fields': list(document.values()), 'line_items': lines}
