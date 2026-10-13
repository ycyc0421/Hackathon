"""VL output boundaries: grid ownership, evidence, failures and model routing."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline.paddle_vl_reader import adapt_output, locate_fields
from app.pipeline.paddle_vl_reader import recognize_image
from app.pipeline.paddle_vl_reader import _spatial_parties
from app.pipeline.rows import parse_line_items
from app.pipeline import paddle_reader
from app.pipeline.reader import ReadResult

GRID = '<table><tr><th>ITEM NO.</th><th>DESCRIPTION</th><th>HS CODE</th><th>QTY</th><th>UNIT PRICE</th><th>AMOUNT</th></tr><tr><td>A-1234</td><td>CERAMIC MUG</td><td></td><td>200 PCS</td><td>2.27</td><td>454.00</td></tr></table>'


class VLTests(unittest.TestCase):
    def test_role_cells_and_total_label_preserve_real_goods(self):
        grid = '<table><tr><td>NO.</td><td>DESCRIPTION OF GOODS</td><td>HS CODE</td><td>QUANTITY</td><td>UNIT PRICE</td><td>AMOUNT (USD)</td></tr><tr><td>1</td><td>Cotton T-shirt\\nSKU: CT-2408</td><td>6109.10</td><td>500 PCS</td><td>$2.80</td><td>$1,400.00</td></tr><tr><td colspan="5">TOTAL AMOUNT (USD)</td><td>$1,400.00</td></tr></table>'
        output = self.output(grid)
        output['res']['parsing_res_list'][0]['block_content'] = 'COMMERCIAL INVOICE\nDocument No.: CI-1\nCurrency: USD'
        output['res']['parsing_res_list'].insert(0, {'block_label': 'table', 'block_content': '<table><tr><td>SELLER / EXPORTERNingbo Qihang Export Co., Ltd.No. 168, Road</td><td>BUYER / IMPORTERGlobal Fashion Inc.1234 Broadway</td></tr></table>'})
        result = adapt_output(output)
        self.assertTrue(result.ok, result.error_message)
        self.assertIn('SELLER: Ningbo Qihang Export Co., Ltd.', result.text)
        self.assertIn('BUYER: Global Fashion Inc.', result.text)
        table = parse_line_items(result.text, page=1)
        self.assertEqual(len(table.line_items), 1)
        fields = {field['field_key']: field['normalized_value'] for field in table.line_items[0]['fields']}
        self.assertEqual(fields['item_code'], 'CT-2408')
        self.assertEqual(fields['amount'], 1400)
        self.assertEqual(fields['quantity'], 500)
        self.assertIn('TOTAL AMOUNT (USD)', table.doc_text)
        from app.pipeline.extract import extract_fields
        total = next(field for field in extract_fields(table.doc_text, 'COMMERCIAL_INVOICE') if field['field_key'] == 'total_amount')
        self.assertEqual(total['normalized_value'], 1400)

    def test_packing_total_quantity_does_not_become_money(self):
        grid = '<table><tr><td>DESCRIPTION OF GOODS</td><td>SKU</td><td>QTY</td><td>PKGS</td><td>NET KG</td><td>GROSS KG</td><td>CBM</td></tr><tr><td>Cotton T-shirt</td><td>CT-2408</td><td>500 PCS</td><td>20</td><td>150.00</td><td>170.00</td><td>1.680</td></tr><tr><td colspan="2">TOTAL</td><td>500</td><td>20</td><td>150.00</td><td>170.00</td><td>1.680</td></tr></table>'
        output = self.output(grid)
        output['res']['parsing_res_list'][0]['block_content'] = 'PACKING LIST\nDocument No.: PL-1\nCURRENCY USD'
        result = adapt_output(output)
        self.assertTrue(result.ok, result.error_message)
        table = parse_line_items(result.text, page=1)
        self.assertEqual(len(table.line_items), 1)
        from app.pipeline.extract import extract_fields
        total = next(field for field in extract_fields(table.doc_text, 'PACKING_LIST') if field['field_key'] == 'total_amount')
        self.assertIsNone(total['normalized_value'])

    def test_total_does_not_allow_numeric_spans_or_hide_following_goods(self):
        for footer in ['<tr><td>TOTAL</td><td colspan="5">500</td></tr>', '<tr><td colspan="6">TOTAL</td></tr><tr><td>2</td><td>Extra goods</td><td></td><td>500 PCS</td><td>2.80</td><td>1400</td></tr>']:
            output = self.output(GRID.replace('</table>', footer + '</table>'))
            self.assertTrue(adapt_output(output).failed)

    def test_interleaved_roles_follow_column_regions(self):
        blocks = [
            {'text': 'SELLER / EXPORTER', 'bbox': [0, 0, 100, 20]},
            {'text': 'BUYER / IMPORTER', 'bbox': [200, 0, 100, 20]},
            {'text': 'Global Fashion Inc.', 'bbox': [200, 30, 100, 20]},
            {'text': 'Ningbo Qihang Export Co., Ltd.', 'bbox': [0, 30, 100, 20]}]
        self.assertEqual(_spatial_parties(blocks), ['SELLER: Ningbo Qihang Export Co., Ltd.', 'BUYER: Global Fashion Inc.'])
        blocks[3]['bbox'] = None
        self.assertEqual(_spatial_parties(blocks), [])

    def test_remote_model_version_and_raw_output_are_checked(self):
        import httpx
        output = self.output()
        def respond(request):
            self.assertEqual(request.content, b'original bytes')
            return httpx.Response(200, json={'pipeline_version': 'v1.6', 'failed': False, 'outputs': [output]})
        with patch('app.config.PADDLE_VL_SERVICE_URL', 'http://127.0.0.1:18082'), patch('httpx.post', side_effect=lambda url, **kw: httpx.Client(transport=httpx.MockTransport(respond)).post(url, content=kw['content'])):
            result = recognize_image(b'original bytes')
        self.assertTrue(result.ok)
        self.assertEqual(result.model_outputs, [output])
        with patch('app.config.PADDLE_VL_SERVICE_URL', 'http://127.0.0.1:18082'), patch('httpx.post', return_value=httpx.Response(200, request=httpx.Request('POST','http://localhost/parse'), json={'pipeline_version': 'wrong', 'outputs': [output]})):
            self.assertFalse(recognize_image(b'original bytes').ok)

    def output(self, grid=GRID):
        return {'res': {'parsing_res_list': [
            {'block_label': 'text', 'block_content': 'COMMERCIAL INVOICE\nDocument No.: CI-1\nCurrency: USD\nTOTAL AMOUNT: 454.00', 'block_bbox': [0, 0, 300, 100]},
            {'block_label': 'table', 'block_content': grid, 'block_bbox': [0, 100, 300, 200]}]}}

    def test_blank_hs_retains_quantity_amount_and_original_output(self):
        output = self.output()
        result = adapt_output(output)
        self.assertTrue(result.ok, result.error_message)
        table = parse_line_items(result.text, page=1)
        self.assertEqual(len(table.line_items), 1)
        fields = {field['field_key']: field for field in table.line_items[0]['fields']}
        self.assertIsNone(fields['hs_code']['normalized_value'])
        self.assertEqual(fields['quantity']['normalized_value'], 200)
        self.assertEqual(fields['amount']['normalized_value'], 454)
        self.assertEqual(result.model_outputs, [output])
        locate_fields([], table.line_items, result.source_blocks)
        self.assertEqual(fields['quantity']['bbox'], [0, 100, 300, 100])
        self.assertEqual(fields['quantity']['bbox_unit'], 'PX')

    def test_multiple_goods_tables_fail_instead_of_selecting_one(self):
        output = self.output()
        output['res']['parsing_res_list'].append(output['res']['parsing_res_list'][1].copy())
        result = adapt_output(output)
        self.assertFalse(result.ok)
        self.assertEqual(result.model_outputs, [output])

    def test_empty_output_fails_and_repeated_evidence_has_no_guessed_box(self):
        self.assertFalse(adapt_output({'res': {'parsing_res_list': []}}).ok)
        field = {'raw_value': 'USD', 'bbox': None, 'page': None}
        locate_fields([field], [], [{'text': 'USD', 'page': i, 'label': 'text', 'bbox': [1, 2, 3, 4]} for i in [1, 2]])
        self.assertIsNone(field['bbox'])
        self.assertIsNone(field['page'])

    def test_vl_failure_does_not_silently_call_legacy(self):
        with patch('app.config.PADDLE_OCR_ENGINE', 'vl'), patch('app.pipeline.paddle_vl_reader.recognize_image', return_value=ReadResult(failed=True, error_message='model failed')), patch.object(paddle_reader, '_recognize_image') as legacy:
            self.assertFalse(paddle_reader.read_image(b'image').ok)
            legacy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
