"""Regression against the fixed original inputs supplied in issue #38. No OCR models."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline.reader import read_document
from app.pipeline.rows import parse_line_items
from app.pipeline.extract import extract_fields, _m_net_weight
from app.pipeline.classify import classify
from app.pipeline.align import align_items
from app.pipeline.compare import build_comparisons, build_item_comparisons
from app.pipeline.trade_json import parse_trade_json
from app.pipeline.paddle_reader import _table_lines, _table_start, _structured_parties
ROOT = Path(__file__).resolve().parents[1] / 'samples/review38'


class Review38(unittest.TestCase):
    def test_net_weight_requires_whole_label(self):
        self.assertIsNone(_m_net_weight('INTERNET: 150 KG'))
        self.assertEqual(_m_net_weight('NET WEIGHT: 150 KG').raw_value, '150 KG')
        self.assertEqual(_m_net_weight('N.W.: 150 KG').raw_value, '150 KG')

    def test_unverified_description_preserves_values_without_match(self):
        docs = [{'file_id': key, 'file_name': key + '.pdf', 'doc_type': 'COMMERCIAL_INVOICE',
                 'process_status': 'EXTRACTED'} for key in ('f1', 'f2')]
        table = 'NO.   ITEM NO.   DESCRIPTION   QTY\n1   CT-2408   Cotton shirt   500 PCS\nTOTAL: 500 PCS'
        extractions = [{'file_id': d['file_id'], 'fields': [],
                        'line_items': parse_line_items(table, page=1).line_items} for d in docs]
        items = align_items(extractions, docs)
        comparisons = build_item_comparisons(items, docs, extractions, lambda *_: False,
                                            unchecked_descriptions={('f1', 1)})
        description = next(c for c in comparisons if c['field_key'] == 'description')
        self.assertEqual(description['status'], 'NOT_CHECKED')
        self.assertTrue(description['note'])
        self.assertTrue(all(v['normalized_value'] for v in description['values']))
        for extraction in extractions:
            field = next(f for f in extraction['line_items'][0]['fields'] if f['field_key'] == 'description')
            self.assertEqual(field['status'], 'EXTRACTED')

    def test_subject_cells_override_interleaved_reading_order(self):
        html = ('<table><tr><td>SELLER / EXPORTER Harbor Industrial Co., Ltd.</td>'
                '<td>BUYER / IMPORTER Aster Distribution Inc.</td></tr></table>')
        ordinary = ['SELLER / EXPORTER', 'BUYER / IMPORTER',
                    'Aster Distribution Inc.', 'Harbor Industrial Co., Ltd.']
        text = '\n'.join(_structured_parties(ordinary, html))
        fields = {f['field_key']: f for f in extract_fields(text, 'COMMERCIAL_INVOICE', page=1)}
        self.assertEqual(fields['shipper']['raw_value'], 'Harbor Industrial Co., Ltd.')
        self.assertEqual(fields['consignee']['raw_value'], 'Aster Distribution Inc.')
        unmapped = {f['field_key']: f for f in extract_fields('\n'.join(ordinary), 'COMMERCIAL_INVOICE')}
        self.assertEqual(unmapped['shipper']['status'], 'UNRECOGNIZED')
        self.assertEqual(unmapped['consignee']['status'], 'UNRECOGNIZED')

    @unittest.skipIf(os.name == 'nt', 'HTTP end-to-end executes on Linux CI/server')
    def test_original_pdfs_through_http_and_report(self):
        from fastapi.testclient import TestClient
        from app import main
        from app.pipeline import runner
        from app.sqlite_store import TaskStore
        from app.models import CheckTask
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = TaskStore(root / 'tasks.db', root / 'legacy')
            with patch.object(main, 'store', store), patch.object(runner, 'store', store), patch.object(runner, 'UPLOAD_DIR', root / 'uploads'):
                with TestClient(main.app) as client:
                    result = client.post('/api/v1/checks', data={'destination_country': 'US'}, files=[
                        ('files', (p.name, p.read_bytes(), 'application/pdf')) for p in sorted(ROOT.glob('*.pdf'))])
                    self.assertEqual(result.status_code, 200, result.text)
                    task = store.get(result.json()['task_id'])
                    CheckTask.model_validate(task)
                    self.assertEqual(task['status'], 'COMPLETED')
                    self.assertEqual(len(task['items']), 3)
                    self.assertEqual(task['summary']['conflict_count'], 1)
                    report = client.get(f"/api/v1/checks/{task['task_id']}/report?format=json")
                    self.assertEqual(report.status_code, 200)
                    self.assertEqual(report.json()['task']['summary']['conflict_count'], 1)

    def test_original_pdf_values_and_quantity_conflict(self):
        docs, extractions = [], []
        for number, path in enumerate(sorted(ROOT.glob('*.pdf')), 1):
            result = read_document(path.name, path.read_bytes())
            self.assertEqual(result.parse_method.value, 'TEXT_LAYER')
            table = parse_line_items(result.text, page=1)
            self.assertFalse(table.suspected)
            self.assertEqual(len(table.line_items), 3)
            kind = classify(result.text, path.name)
            fields = extract_fields(table.doc_text, kind, page=1, row_keys=table.header_keys)
            by_key = {f['field_key']: f for f in fields}
            self.assertEqual(by_key['shipper']['normalized_value'], 'HARBOR DISTRIBUTION 0002 CO., LTD')
            self.assertEqual(by_key['consignee']['normalized_value'], 'JUNIPER IMPORT 1002 INC')
            expected_no = {'commercial_invoice': 'CI-00002', 'packing_list': 'PL-00002', 'proforma_invoice': 'PI-00002'}[path.stem]
            self.assertEqual(by_key['document_no']['normalized_value'], expected_no)
            self.assertEqual(by_key['document_no']['page'], 1)
            if path.stem == 'packing_list':
                for key, value in [('packages', 55), ('net_weight', 463.6), ('gross_weight', 503.43), ('volume', 1.073)]:
                    self.assertEqual(by_key[key]['normalized_value'], value, key)
                self.assertIsNone(by_key['total_amount']['normalized_value'])
                self.assertEqual([next(f['normalized_value'] for f in r['fields'] if f['field_key'] == 'packages') for r in table.line_items], [22, 25, 8])
            else:
                self.assertEqual(by_key['total_amount']['normalized_value'], 5049.6)
                self.assertEqual(by_key['total_amount']['unit'], 'GBP')
            for row in table.line_items:
                quantity = next(f for f in row['fields'] if f['field_key'] == 'quantity')
                self.assertEqual(quantity['page'], 1)
                self.assertIn(str(int(quantity['normalized_value'])), quantity['raw_text'])
            docs.append({'file_id': f'f{number}', 'file_name': path.name, 'doc_type': kind, 'process_status': 'EXTRACTED'})
            extractions.append({'file_id': f'f{number}', 'fields': fields, 'line_items': table.line_items})
        items = align_items(extractions, docs)
        self.assertEqual(len(items), 3)
        comparisons = build_comparisons(docs, extractions, lambda *_: False)
        self.assertFalse(any(c['field_key'] == 'document_no' for c in comparisons))
        comparisons += build_item_comparisons(items, docs, extractions, lambda *_: False)
        quantities = [c for c in comparisons if c['field_key'] == 'quantity' and c.get('scope') == 'ITEM']
        self.assertEqual([c['status'] for c in quantities].count('CONFLICT'), 1)
        conflict = next(c for c in quantities if c['status'] == 'CONFLICT')
        self.assertEqual(sorted(v['normalized_value'] for v in conflict['values']), [880, 880, 888])

    def test_json_missing_quantity_and_defensive_comparison(self):
        docs, extractions = [], []
        for number, name in enumerate(['commercial_invoice.json', 'packing_list.json'], 1):
            parsed = parse_trade_json((ROOT / name).read_bytes())
            parsed['file_id'] = f'f{number}'
            docs.append({'file_id': f'f{number}', 'file_name': name, 'doc_type': parsed['doc_type'], 'process_status': 'EXTRACTED'})
            extractions.append(parsed)
        field = next(f for f in extractions[1]['line_items'][1]['fields'] if f['field_key'] == 'quantity')
        self.assertEqual(field['status'], 'MISSING_IN_DOC')
        items = align_items(extractions, docs)
        for remove in [False, True]:
            probe = copy.deepcopy(extractions)
            if remove:
                probe[1]['line_items'][1]['fields'] = [f for f in probe[1]['line_items'][1]['fields'] if f['field_key'] != 'quantity']
            comparisons = build_item_comparisons(items, docs, probe, lambda *_: False)
            quantities = [c for c in comparisons if c['field_key'] == 'quantity']
            self.assertEqual([c['status'] for c in quantities], ['MATCH', 'MISSING_IN_SOME'])
            self.assertEqual(len(quantities[1]['values']), 2)

    def test_saved_dual_table_and_title_span(self):
        lines = _table_lines((ROOT / 'packing-list-ocr.md').read_text(encoding='utf-8'))
        parsed = parse_line_items('\n'.join(lines) + '\nTOTAL: 55 CARTONS', page=1)
        self.assertEqual(len(parsed.line_items), 3)
        self.assertFalse(parsed.suspected)
        html = '<table><tr><td colspan="2">INVOICE</td></tr><tr><td>SKU</td><td>QTY</td></tr><tr><td>A1</td><td>500</td></tr></table>'
        self.assertEqual(_table_lines(html), ['SKU   QTY', 'A1   500'])
        with self.assertRaises(ValueError):
            _table_lines('<table><tr><td>SKU</td><td>QTY</td></tr><tr><td>A1</td><td rowspan="2">500</td></tr><tr><td>A2</td></tr></table>')

    def test_amount_header_never_reads_next_line_and_net_is_not_gross(self):
        fields = {f['field_key']: f for f in extract_fields('AMOUNT\n1\nNET 463.60 KG', 'PACKING_LIST')}
        self.assertIsNone(fields['total_amount']['normalized_value'])
        self.assertIsNone(fields['gross_weight']['normalized_value'])
        self.assertEqual(fields['net_weight']['normalized_value'], 463.6)

    def test_html_empty_hs_keeps_quantity_and_amount_in_their_columns(self):
        html = ('<table><tr><td>NO.</td><td>ITEM NO.</td><td>DESCRIPTION</td>'
                '<td>HS CODE</td><td>QTY</td><td>UNIT PRICE</td><td>AMOUNT</td></tr>'
                '<tr><td>1</td><td>CT-2408</td><td>SHIRT</td><td></td>'
                '<td>500 PCS</td><td>2.80</td><td>1400.00</td></tr></table>')
        table = parse_line_items('\n'.join(_table_lines(html)) + '\nTOTAL AMOUNT 1400.00', page=1)
        self.assertFalse(table.suspected)
        self.assertEqual(len(table.line_items), 1)
        fields = {field['field_key']: field for field in table.line_items[0]['fields']}
        self.assertEqual(fields['hs_code']['status'], 'MISSING_IN_DOC')
        self.assertEqual(fields['quantity']['normalized_value'], 500)
        self.assertEqual(fields['amount']['normalized_value'], 1400)
        self.assertEqual(fields['quantity']['page'], 1)


if __name__ == '__main__':
    unittest.main()
