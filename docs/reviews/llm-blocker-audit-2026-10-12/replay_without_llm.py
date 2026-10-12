"""Replay saved OCR outputs through a selected backend; never load a model."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import argparse
import json
import os
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--repo', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--evidence')
parser.add_argument('--originals')
args = parser.parse_args()
os.environ['PADDLE_OCR_ENABLED'] = '1'
sys.stdout.reconfigure(encoding='utf-8')
repo = Path(args.repo)
root = Path(__file__).resolve().parent
evidence_dir = Path(args.evidence) if args.evidence else root / 'evidence'
originals_dir = Path(args.originals) if args.originals else root / 'originals'
sys.path.insert(0, str(repo / 'backend'))
from app.pipeline import paddle_reader, reader
from app.pipeline.classify import classify
from app.pipeline.extract import extract_fields
from app.pipeline.rows import parse_line_items

assert reader.PADDLE_OCR_ENABLED
outputs = []
for kind, filename in (
    ('pi', 'exportdoc-proforma-invoice-sample.pdf'),
    ('ci', 'exportdoc-commercial-invoice-sample.pdf'),
    ('pl', 'exportdoc-packing-list-sample.pdf'),
):
    raw_dir = evidence_dir / 'shirt'
    lines = (raw_dir / f'{kind}-ocr.txt').read_text(encoding='utf-8').splitlines()
    markdown = (raw_dir / f'{kind}-structure.md').read_text(encoding='utf-8')
    ordinary = SimpleNamespace(predict=lambda **kwargs: [SimpleNamespace(json={'res': {'rec_texts': lines}})])
    structure = SimpleNamespace(predict=lambda **kwargs: [SimpleNamespace(markdown={'markdown_texts': markdown})])
    try:
        table = paddle_reader._table_lines(markdown)
        grid = {'accepted': True, 'rows': table}
    except ValueError as error:
        grid = {'accepted': False, 'error': str(error)}
    # The PDF render uses actual original bytes. Predictions are saved-output
    # mocks; this is an adapter replay, not a new OCR or model evaluation.
    original = originals_dir / filename
    with patch.object(paddle_reader, '_get_ocr', return_value=ordinary), \
         patch.object(paddle_reader, '_get_structure', return_value=structure), \
         patch.object(reader, '_transcribe_with_llm', side_effect=AssertionError('LLM forbidden in this replay')) as llm:
        recognized = reader._read_pdf(original.read_bytes())
        assert llm.call_count == 0
    record = {'file': filename, 'model_inference_performed': False, 'external_llm_calls': 0, 'read_ok': recognized.ok, 'error': recognized.error_message, 'uncertain_item_codes': recognized.uncertain_item_codes, 'structured_grid': grid, 'adapted_text': recognized.text}
    if recognized.ok:
        table = parse_line_items(recognized.text, page=1)
        doc_type = classify(recognized.text, filename)
        fields = extract_fields(table.doc_text, doc_type, page=1, row_keys=table.header_keys or None)
        values = {f['field_key']: f for f in fields}
        assert not table.suspected and len(table.line_items) == 1
        row = {f['field_key']: f for f in table.line_items[0]['fields']}
        expected = {'item_code': 'CT-2408', 'quantity': 500}
        expected.update({'packages': 20, 'net_weight': 150, 'gross_weight': 170, 'volume': 1.68} if kind == 'pl' else {'unit_price': 2.8, 'amount': 1400})
        for key, value in expected.items():
            assert row[key]['normalized_value'] == value, (filename, key, row[key])
        assert row['description']['raw_value'] == '100% Cotton T-shirt, unisex, assorted colors'
        assert values['shipper']['normalized_value'] == 'NINGBO QIHANG EXPORT CO., LTD'
        assert values['consignee']['normalized_value'] == 'GLOBAL FASHION INC'
        if kind == 'pl':
            assert values['total_amount']['normalized_value'] is None
            assert values['total_amount']['status'] == 'NOT_IN_DOC'
        else:
            assert values['total_amount']['normalized_value'] == 1400
        record['backend_values_verified'] = True
        record['expected_values'] = expected
        record['description_raw_value'] = row['description']['raw_value']
    outputs.append(record)
    print(json.dumps({key: value for key, value in record.items() if key != 'adapted_text'}, ensure_ascii=False))
result = {'repository_sha': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(), 'source': 'saved initial diagnostic OCR text and PPStructure markdown', 'scope': 'model-free adapter replay on original PDF rendering; not new inference or HTTP acceptance', 'results': outputs}
Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
