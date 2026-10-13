"""PaddleOCR-VL main model: retain region output and adapt explicit HTML grids."""
from html import unescape
from io import BytesIO
import re
import math
from threading import Lock

from .. import config
from ..models import ParseMethod
from .reader import ReadResult
from .paddle_reader import _TableParser, _table_lines, _structured_parties

_model = None
_lock = Lock()


def _get_model():
    global _model
    with _lock:
        if _model is None:
            if not 1 <= config.PADDLE_VL_CPU_THREADS <= 8:
                raise ValueError('PADDLE_VL_CPU_THREADS 必须在 1 至 8 之间')
            import paddle
            paddle.set_flags({'FLAGS_paddle_num_threads': config.PADDLE_VL_CPU_THREADS})
            from paddleocr import PaddleOCRVL
            kwargs = dict(pipeline_version=config.PADDLE_VL_VERSION,
                          device=config.PADDLE_VL_DEVICE, cpu_threads=config.PADDLE_VL_CPU_THREADS,
                          enable_mkldnn=False, use_doc_orientation_classify=False,
                          use_doc_unwarping=False, use_queues=False)
            if config.PADDLE_VL_REC_BACKEND == 'llama-cpp-server':
                if not config.PADDLE_VL_REC_SERVER_URL:
                    raise ValueError('llama-cpp-server 缺少 PADDLE_VL_REC_SERVER_URL')
                kwargs.update(vl_rec_backend='llama-cpp-server',
                              vl_rec_server_url=config.PADDLE_VL_REC_SERVER_URL,
                              vl_rec_max_concurrency=1)
            elif config.PADDLE_VL_REC_BACKEND != 'native':
                raise ValueError('不支持的 VL 推理引擎')
            if config.PADDLE_VL_MODEL_DIR:
                kwargs['vl_rec_model_dir'] = config.PADDLE_VL_MODEL_DIR
            if config.PADDLE_VL_LAYOUT_DIR:
                kwargs['layout_detection_model_dir'] = config.PADDLE_VL_LAYOUT_DIR
            _model = PaddleOCRVL(**kwargs)
        return _model


def _plain(content):
    content = content.replace(r'\n', '\n')
    content = re.sub(r'<(?:br\s*/?|/tr|/p|/div)>', '\n', content, flags=re.I)
    content = re.sub(r'</t[dh]>', '\n', content, flags=re.I)
    return unescape(re.sub(r'<[^>]+>', '', content)).strip()


def _spatial_parties(blocks):
    """Use unique same-column company regions below separate role labels."""
    company_re = r'[^\n]+?(?:Co\.?\s*,?\s*Ltd\.?|Inc\.?|Limited|LLC)(?=\s|$)'
    mapped = {}
    for role, pattern in [('SELLER', r'(?:SELLER|SHIPPER)\s*/\s*EXPORTER'),
                          ('BUYER', r'(?:BUYER|CONSIGNEE)\s*/\s*IMPORTER')]:
        labels = [block for block in blocks if re.search(pattern, block['text'], re.I)]
        if len(labels) != 1:
            continue
        label = labels[0]
        tail = re.split(pattern, label['text'], maxsplit=1, flags=re.I)[1].strip(' :：\n')
        if re.search(r'(SELLER|BUYER|SHIPPER|CONSIGNEE)', tail, re.I):
            continue
        company = re.match(company_re, tail, re.I)
        if company:
            mapped[role] = company.group().strip()
            continue
        box = label['bbox']
        if not box or re.search(r'(SELLER|BUYER|SHIPPER|CONSIGNEE)', tail, re.I):
            continue
        candidates = []
        for block in blocks:
            other = block['bbox']
            company = re.match(company_re, block['text'], re.I)
            if not other or not company:
                continue
            overlap = min(box[0]+box[2], other[0]+other[2])-max(box[0], other[0])
            gap = other[1]-(box[1]+box[3])
            if overlap >= .6*min(box[2], other[2]) and -5 <= gap <= 200:
                candidates.append((gap, company.group().strip()))
        candidates.sort()
        if candidates and (len(candidates) == 1 or candidates[1][0]-candidates[0][0] > 10):
            mapped[role] = candidates[0][1]
    if set(mapped) == {'SELLER', 'BUYER'} and mapped['SELLER'].casefold() != mapped['BUYER'].casefold():
        return [f'{role}: {mapped[role]}' for role in ('SELLER', 'BUYER')]
    return []


def _html_parties(html):
    """Read companies inside their own explicit role cell, never across columns."""
    parser = _TableParser()
    parser.feed(html)
    mapped = {}
    labels = [('SELLER', r'(?:SELLER|SHIPPER)\s*/\s*EXPORTER'),
              ('BUYER', r'(?:BUYER|CONSIGNEE)\s*/\s*IMPORTER')]
    for table in parser.tables:
        for row in table:
            for cell in row:
                for role, pattern in labels:
                    label = re.match(pattern + r'\s*[:：]?\s*', cell, re.I)
                    if label is None:
                        continue
                    value = cell[label.end():]
                    if re.search(r'(SELLER|BUYER|SHIPPER|CONSIGNEE)\s*/', value, re.I):
                        continue
                    company = re.match(r'[^\n]+?(?:Co\.?\s*,?\s*Ltd\.?|Inc\.?|Limited|LLC)(?=\s|$|No\.?\s*\d|\d)', value, re.I)
                    if company:
                        mapped.setdefault(role, set()).add(company.group().strip())
    if set(mapped) == {'SELLER', 'BUYER'} and all(len(values) == 1 for values in mapped.values()):
        seller, buyer = next(iter(mapped['SELLER'])), next(iter(mapped['BUYER']))
        if seller.casefold() != buyer.casefold():
            return [f'SELLER: {seller}', f'BUYER: {buyer}']
    return []


def adapt_output(output: dict) -> ReadResult:
    raw = output.get('res', output)
    blocks = raw.get('parsing_res_list')
    if not isinstance(blocks, list) or not blocks:
        return ReadResult(failed=True, error_message='VL 未返回版面识别块', model_outputs=[output])
    source, ordinary, html = [], [], []
    for block in blocks:
        content = block.get('block_content')
        if not isinstance(content, str):
            return ReadResult(failed=True, error_message='VL 版面块内容类型无效', model_outputs=[output])
        label = block.get('block_label')
        text = _plain(content)
        ordinary.extend(line.strip() for line in text.splitlines() if line.strip())
        if re.search(r'<table\b', content, re.I):
            html.append(content.replace(r'\n', '\n'))
        coords = block.get('block_bbox')
        bbox = None
        if isinstance(coords, list) and len(coords) == 4:
            x1, y1, x2, y2 = coords
            if all(isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in coords) and 0 <= x1 < x2 and 0 <= y1 < y2:
                bbox = [float(x1), float(y1), float(x2-x1), float(y2-y1)]
        source.append({'page': 1, 'label': label, 'text': text, 'bbox': bbox})
    try:
        table_rows = _table_lines('\n'.join(html)) if html else None
    except ValueError as exc:
        # Party-only HTML is valid; a suspected goods grid must not disappear.
        from .rows import _looks_like_header
        parser = _TableParser()
        parser.feed('\n'.join(html))
        if any(any(_looks_like_header('   '.join(row)) for row in table[:3]) for table in parser.tables):
            return ReadResult(failed=True, page_count=1, error_message='无法可靠读取商品表格，请核对原件版式或提供更清晰的文件',
                              model_outputs=[output], source_blocks=source)
        table_rows = None
    lines = _structured_parties(ordinary, '\n'.join(html)) if html else ordinary
    if lines == ordinary:
        lines = (_html_parties('\n'.join(html)) or _spatial_parties(source)) + ordinary
    if table_rows:
        # Preserve non-goods blocks separately; do not flatten goods cells into ticket values.
        goods_texts = set()
        from .rows import _looks_like_header
        for block in blocks:
            parser = _TableParser()
            parser.feed(block['block_content'])
            if any(any(_looks_like_header('   '.join(row)) for row in table[:3]) for table in parser.tables):
                goods_texts.update(_plain(block['block_content']).splitlines())
        lines = [line for line in lines if line not in goods_texts] + table_rows
    text = '\n'.join(lines)
    if len(text.strip()) < config.MIN_TEXT_LAYER_CHARS:
        return ReadResult(failed=True, page_count=1, error_message='VL 识别文字过少', model_outputs=[output])
    return ReadResult(text=text, page_count=1, page_texts=[text], parse_method=ParseMethod.OCR,
                      model_outputs=[output], source_blocks=source)


def recognize_image(data: bytes) -> ReadResult:
    try:
        if config.PADDLE_VL_SERVICE_URL:
            import httpx
            response = httpx.post(config.PADDLE_VL_SERVICE_URL + '/parse', content=data,
                                  headers={'Content-Type': 'application/octet-stream'}, timeout=config.PADDLE_VL_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            if payload.get('pipeline_version') != config.PADDLE_VL_VERSION:
                raise ValueError('VL 服务版本与后端配置不一致')
            if payload.get('failed'):
                return ReadResult(failed=True, page_count=1, error_message='识别服务未能完成此文件的解析，请稍后重试',
                                  model_outputs=payload.get('outputs', []))
            outputs = payload.get('outputs')
            if not isinstance(outputs, list) or len(outputs) != 1:
                raise ValueError('VL 服务未返回唯一单页输出')
            return adapt_output(outputs[0])
        from PIL import Image
        import numpy as np
        image = Image.open(BytesIO(data))
        if getattr(image, 'n_frames', 1) != 1:
            raise ValueError('多帧图片尚不支持')
        results = list(_get_model().predict(input=np.asarray(image.convert('RGB'))))
        if len(results) != 1:
            raise ValueError('VL 未返回唯一单页结果')
        return adapt_output(results[0].json)
    except Exception as exc:
        from ..public_errors import log
        log.exception("VL document recognition failed")
        return ReadResult(failed=True, page_count=1, error_message='识别服务未能完成此文件的解析，请稍后重试')


def locate_fields(fields: list[dict], rows: list[dict], blocks: list[dict]):
    for row, group in [(False, fields)] + [(True, item['fields']) for item in rows]:
        for field in group:
            value = field.get('raw_value')
            page = field.get('page')
            # 页码由逐页抽取确定；不能用其他页的同值覆盖或猜测来源。
            if not value or not value.strip() or page is None:
                continue
            pattern = (r'(?<![\w.,/-])' + r'\s*'.join(re.escape(part) for part in value.split())
                       + r'(?![\w.,/-])')
            candidates = [block for block in blocks if block['page'] == page
                          and re.search(pattern, block['text'], re.I)
                          and (not row or block['label'] == 'table')]
            if len(candidates) == 1:
                if candidates[0]['bbox'] is not None:
                    field['bbox'] = candidates[0]['bbox']
                    field['bbox_unit'] = 'PX'
