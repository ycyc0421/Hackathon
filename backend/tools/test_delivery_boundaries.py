"""Review #46: country values, container evidence and interrupted originals."""
import sys
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from app import main
from app.sqlite_store import TaskStore
from app.pipeline import normalize as N
from app.pipeline.extract import extract_fields
from app.pipeline.rows import parse_line_items


class DeliveryTests(unittest.TestCase):
    def test_admission_is_bounded_and_queued_inputs_are_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slots = threading.BoundedSemaphore(4)
            with patch.object(main, 'store') as store, patch.object(main, '_read_limited', new=AsyncMock(return_value=b'original')), patch.object(main, '_load_task'), patch.object(main, 'dump'), patch.object(main, 'to_frontend_task'), patch.object(main, 'UPLOAD_DIR', root/'uploads'), patch.object(main, '_check_slots', slots), patch.object(main, '_check_executor') as executor, patch.object(main, 'POST_WAIT_MS', 0):
                store.next_seq.side_effect = range(1, 6)
                def submit():
                    # All awaits are mocked and POST waiting is disabled here.
                    # Drive the handler without creating a socket-based event loop.
                    coroutine = main.create_check(files=[UploadFile(io.BytesIO(b'original'), filename='sample.txt')], destination_country='SG', destination_country_name=None, trade_mode=None, declared_currency=None, notes=None)
                    try:
                        coroutine.send(None)
                    except StopIteration as result:
                        return result.value
                    finally:
                        coroutine.close()
                    self.fail('Unexpected asynchronous work in admission unit test')
                for _ in range(4):
                    submit()
                with self.assertRaises(main.ApiError) as rejected:
                    submit()
                self.assertEqual(rejected.exception.status_code, 429)
                self.assertEqual(executor.submit.call_count, 4)
                for call in executor.submit.call_args_list:
                    self.assertIsInstance(call.args[2][0][1], Path)
                    self.assertEqual(call.args[2][0][1].read_bytes(), b'original')
                with patch.object(main, 'run_check', side_effect=RuntimeError('inference failed')):
                    with self.assertRaises(RuntimeError):
                        main._run_reserved_check('test', [])
                self.assertTrue(slots.acquire(blocking=False))
                self.assertFalse(slots.acquire(blocking=False))

    def test_countries_supported_by_requests_normalize_from_documents(self):
        for raw, expected in [('Singapore', 'SG'), ('SG', 'SG'), ('新加坡', 'SG'),
                              ('Australia', 'AU'), ('AU', 'AU'), ('澳大利亚', 'AU')]:
            self.assertEqual(N.to_country(raw), expected)

    def test_generic_packaging_is_not_assumed_to_be_cartons(self):
        for raw in ['20', '20 PKGS', '20 PACKAGES']:
            self.assertEqual(N.to_measure(raw, 'packages'), (20, None))
        self.assertEqual(N.to_measure('20 CTNS', 'packages'), (20, 'CARTON'))
        for header, unit in [('PKGS', None), ('CARTONS', 'CARTON')]:
            table = parse_line_items(f'NO.   ITEM NO.   DESCRIPTION   QTY   {header}\n1   A-123   Cotton T-shirt   500 PCS   20', page=1)
            package = next(field for field in table.line_items[0]['fields'] if field['field_key'] == 'packages')
            self.assertEqual(package['unit'], unit)
        package = next(field for field in extract_fields('TOTAL CARTONS: 20', 'PACKING_LIST') if field['field_key'] == 'packages')
        self.assertEqual(package['unit'], 'CARTON')

    def test_every_original_survives_interruption_before_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = TaskStore(root/'tasks.db', root/'legacy')
            originals = [('first.pdf', b'first bytes'), ('../second.pdf', b'second bytes'), ('third.edi', b'UNH+1')]
            with patch.object(main, 'store', store), patch.object(main, 'UPLOAD_DIR', root/'uploads'), patch.object(main, 'run_check'), patch.object(main, 'POST_WAIT_MS', 0), TestClient(main.app) as client:
                task = client.post('/api/v1/checks', data={'destination_country': 'SG'},
                                   files=[('files', (name, value)) for name, value in originals]).json()
                self.assertEqual(task['status'], 'PENDING')
                self.assertEqual(len(task['documents']), 3)
                for index, (_, value) in enumerate(originals, 1):
                    self.assertEqual(client.get(f"/api/v1/checks/{task['task_id']}/files/f{index}").content, value)
                # Execute the same recovery hook used by the API startup.
                recovered = TaskStore(root/'tasks.db', root/'legacy')
                recovered.recover_interrupted()
                with patch.object(main, 'store', recovered):
                    final = client.get('/api/v1/checks/'+task['task_id']).json()
                    self.assertEqual(final['status'], 'FAILED')
                    self.assertEqual({doc['process_status'] for doc in final['documents']}, {'FAILED'})
                    self.assertEqual(final['summary']['document_count'], 3)
                    for index, (_, value) in enumerate(originals, 1):
                        self.assertEqual(client.get(f"/api/v1/checks/{task['task_id']}/files/f{index}").content, value)


if __name__ == '__main__':
    unittest.main()
