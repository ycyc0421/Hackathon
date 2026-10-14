import json
import sys
import unittest
import os
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline.trade_json import parse_trade_json, FORMAT
from app.pipeline.reader import read_document, guess_file_type
from app.models import Extraction


class TradeJsonTests(unittest.TestCase):
    def sample(self):
        return {"format": FORMAT, "doc_type": "COMMERCIAL_INVOICE", "fields": {"invoice_no": "INV-1", "currency": "USD", "gross_weight": "10 KGS"}, "line_items": [{"item_no": 1, "fields": {"item_code": "A1", "description": "CERAMIC MUG WHITE", "amount": "10.00"}}]}

    def test_structured_preserves_values_and_contract(self):
        result = parse_trade_json(json.dumps(self.sample()).encode())
        Extraction.model_validate({"file_id": "f1", "parse_method": "EDI_PARSE", **result})
        amount = result["line_items"][0]["fields"][2]
        self.assertEqual((amount["raw_value"], amount["normalized_value"], amount["unit"]), ("10.00", 10, "USD"))
        self.assertIsNone(amount["confidence"])

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            parse_trade_json(b'{"format":"a","format":"b"}')

    def test_unknown_and_invalid_rows_rejected(self):
        for change in (lambda x: x.update(unknown="x"), lambda x: x["line_items"].append(x["line_items"][0]), lambda x: x["line_items"][0].update(item_no=True), lambda x: x["fields"].update(currency=123)):
            data = self.sample()
            change(data)
            with self.assertRaises(ValueError):
                parse_trade_json(json.dumps(data).encode())

    def test_no_standard_edi_claim(self):
        self.assertEqual(guess_file_type("standard.edi").value, "EDI")
        self.assertEqual(guess_file_type("standard.x12").value, "OTHER")
        self.assertTrue(read_document("standard.edi", b"UNB+UNOC").failed)
        self.assertTrue(read_document("bad.json", b'{"format":"UN/EDIFACT"}').failed)

    def test_bad_number_explicit(self):
        data=self.sample()
        data["fields"]["gross_weight"]="UNKNOWN"
        result=parse_trade_json(json.dumps(data).encode())
        field=next(f for f in result["fields"] if f["field_key"]=="gross_weight")
        self.assertEqual(field["status"], "NORMALIZE_FAILED")
        self.assertIsNone(field["normalized_value"])

    @unittest.skipIf(os.name == 'nt', 'HTTP integration runs on Linux CI')
    def test_http_pipeline_and_schema(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.sqlite_store import TaskStore
        from app.models import CheckTask
        with TemporaryDirectory() as directory:
            store=TaskStore(Path(directory)/'tasks.db',Path(directory)/'legacy')
            with patch('app.main.store',store), patch('app.pipeline.runner.store',store), patch('app.pipeline.runner.UPLOAD_DIR',Path(directory)/'uploads'):
                with TestClient(app) as client:
                    response=client.post('/api/v1/checks',data={'destination_country':'DE'},files=[('files',('invoice.json',json.dumps(self.sample()).encode(),'application/json'))])
                    self.assertEqual(response.status_code,200,response.text)
                    task=store.get(response.json()['task_id'])
                    self.assertEqual(task['status'],'COMPLETED')
                    CheckTask.model_validate(task)
                    self.assertEqual(task['extractions'][0]['parse_method'],'EDI_PARSE')
                    self.assertEqual(len(task['extractions'][0]['line_items']),1)
                    duplicate = self.sample()
                    duplicate['line_items'] *= 2
                    failed = client.post('/api/v1/checks', data={'destination_country': 'DE'},
                        files=[('files', ('duplicate.json', json.dumps(duplicate).encode(), 'application/json'))]).json()
                    self.assertEqual(failed['status'], 'FAILED')
                    reason = '商品行号必须为不重复的正整数'
                    self.assertIn(reason, failed['documents'][0]['error_message'])
                    exported = client.get(f"/api/v1/checks/{failed['task_id']}/report").json()
                    self.assertIn(reason, exported['documents'][0]['error_message'])


if __name__ == '__main__':
    unittest.main()
