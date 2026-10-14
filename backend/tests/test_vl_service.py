"""Verify worker capacity and failure boundaries without downloading weights."""
import sys
import unittest
from pathlib import Path
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import vl_service
from app.pipeline.reader import ReadResult


class WorkerTests(unittest.TestCase):
    def test_busy_requests_do_not_start_parallel_inference(self):
        entered, release = Event(), Event()
        def infer(data):
            entered.set()
            release.wait(5)
            return ReadResult(model_outputs=[{'res': {'parsing_res_list': []}}])
        with patch.object(vl_service.config, 'PADDLE_VL_SERVICE_URL', ''), patch.object(vl_service, '_get_model'), patch.object(vl_service, 'recognize_image', side_effect=infer) as model, TestClient(vl_service.app) as client, ThreadPoolExecutor() as executor:
            pending = executor.submit(client.post, '/parse', content=b'image')
            self.assertTrue(entered.wait(2))
            try:
                self.assertTrue(client.get('/health').json()['busy'])
                response = client.post('/parse', content=b'second')
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['error']['code'], 'MODEL_BUSY')
            finally:
                release.set()
            self.assertEqual(pending.result(2).status_code, 200)
            self.assertFalse(client.get('/health').json()['busy'])
            self.assertEqual(model.call_count, 1)

    def test_oversize_body_is_rejected_before_inference(self):
        with patch.object(vl_service.config, 'PADDLE_VL_SERVICE_URL', ''), patch.object(vl_service.config, 'MAX_FILE_SIZE', 4), patch.object(vl_service, '_get_model'), patch.object(vl_service, 'recognize_image') as model, TestClient(vl_service.app) as client:
            self.assertEqual(client.post('/parse', content=b'large').status_code, 413)
            model.assert_not_called()

    def test_recursive_worker_configuration_refuses_startup(self):
        with patch.object(vl_service.config, 'PADDLE_VL_SERVICE_URL', 'http://127.0.0.1:18082'):
            with self.assertRaisesRegex(RuntimeError, '递归'):
                with TestClient(vl_service.app):
                    pass


if __name__ == '__main__':
    unittest.main()
