"""HTTP regressions for honest capabilities and retained original bytes."""
import json
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import main
from app.pipeline import runner
from app.sqlite_store import TaskStore
from app.workflow import payload_hash


class FileAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = TaskStore(root / 'tasks.db', root / 'legacy')
        self.patches = [patch.object(main, 'store', self.store), patch.object(runner, 'store', self.store),
                        patch.object(main, 'UPLOAD_DIR', root / 'uploads'),
                        patch.object(runner, 'UPLOAD_DIR', root / 'uploads')]
        for item in self.patches:
            item.start()
        self.client = TestClient(main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def upload(self, name, data):
        response = self.client.post('/api/v1/checks', data={'destination_country': 'US'},
                                    files=[('files', (name, data, 'application/octet-stream'))])
        self.assertEqual(response.status_code, 200)
        task_id = response.json()['task_id']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            task = self.store.get(task_id)
            if task['status'] not in {'PENDING', 'PROCESSING'}:
                return task
            time.sleep(.02)
        self.fail('task did not finish')

    def test_capabilities_limit_edifact_and_unconfigured_ocr(self):
        with patch.object(main, 'PADDLE_OCR_ENABLED', False), patch.object(main, 'llm_enabled', return_value=False):
            value = self.client.get('/api/v1/capabilities').json()
        formats = {item['format']: item for item in value['formats']}
        self.assertTrue(formats['UN/EDIFACT']['supported'])
        self.assertIn('INVOIC D96A', formats['UN/EDIFACT']['reason'])
        self.assertFalse(formats['X12']['supported'])
        self.assertFalse(formats['IMAGE']['supported'])
        self.assertFalse(formats['PDF']['scan_ocr_configured'])
        self.assertTrue(formats['hackathon-trade-json-v1']['supported'])
        self.assertFalse(value['txt_as_edi_supported'])

    def test_failed_edi_preserves_original_bytes_and_download_headers(self):
        original = b"UNA:+.? '\nUNH+1+INVOIC:D:96A:UN'FTX+AAI+++A?+B?:C??D'"
        task = self.upload('INVOICE.EDI', original)
        self.assertEqual(task['status'], 'FAILED')
        self.assertEqual(task['documents'][0]['process_status'], 'FAILED')
        response = self.client.get(f"/api/v1/checks/{task['task_id']}/files/f1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, original)
        self.assertIn('attachment', response.headers['content-disposition'])
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(self.client.get(f"/api/v1/checks/{task['task_id']}/files/f9").status_code, 404)

    def test_revision_chain_downloads_source_without_rewriting_it(self):
        original = json.dumps({'format': 'hackathon-trade-json-v1', 'doc_type': 'COMMERCIAL_INVOICE',
                               'fields': {'currency': 'USD', 'invoice_no': 'CI-1'}, 'line_items': []}).encode()
        task = self.upload('invoice.json', original)
        for number, currency in enumerate(['EUR', 'GBP']):
            response = self.client.post(f"/api/v1/checks/{task['task_id']}/corrections", json={
                'request_id': f'review-{number}', 'source_hash': payload_hash(task), 'reason': '回归核对',
                'changes': [{'file_id': 'f1', 'field_key': 'currency', 'value': currency}]})
            self.assertEqual(response.status_code, 200, response.text)
            task = self.store.get(response.json()['task_id'])
        response = self.client.get(f"/api/v1/checks/{task['task_id']}/files/f1")
        self.assertEqual(response.content, original)
        history = self.store.correction_history(task['task_id'])
        source_file = main.UPLOAD_DIR / history[0]['source_task_id'] / 'f1.source'
        source_file.unlink()
        response = self.client.get(f"/api/v1/checks/{task['task_id']}/files/f1")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'SOURCE_NOT_AVAILABLE')

    def test_stored_filename_cannot_escape_task_directory(self):
        task = self.upload('bad.edi', b'UNH')
        task['documents'][0]['file_name'] = '../../../outside.txt'
        self.store.update(task['task_id'], {'documents': task['documents']})
        response = self.client.get(f"/api/v1/checks/{task['task_id']}/files/f1")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'SOURCE_NOT_AVAILABLE')


if __name__ == '__main__':
    unittest.main()
