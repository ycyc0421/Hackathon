"""公网挑战、跨域缺失和任务失败都必须阻止发布。"""

from pathlib import Path
from io import BytesIO
import json
import tempfile
import unittest
from unittest.mock import patch

import httpx

import smoke


class PublicSmokeTests(unittest.TestCase):
    origin = 'https://app.example.com'
    base = 'https://backend.example.com/api/v1'

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)

    def run_probe(self, handler, **kwargs):
        client = httpx.Client(transport=httpx.MockTransport(handler), headers={'Origin': self.origin})
        with patch('smoke.httpx.Client', return_value=client):
            smoke.run(self.base, self.origin, self.output, **kwargs)

    def diagnostic(self):
        return json.loads((self.output / 'probe.diagnostic.json').read_text(encoding='utf-8'))

    def test_edge_challenge_reports_status_without_response_body(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(403, headers={'cf-mitigated': 'challenge'}, text='private response detail')

        with self.assertRaisesRegex(AssertionError, 'HTTP 403.*Cloudflare') as error:
            self.run_probe(handler)
        self.assertNotIn('private response detail', str(error.exception))
        self.assertEqual([request.method for request in requests], ['OPTIONS'])
        self.assertEqual(str(requests[0].url), f'{self.base}/checks')
        self.assertEqual(requests[0].headers['Origin'], self.origin)
        diagnostic = self.diagnostic()
        self.assertEqual(diagnostic['outcome'], 'failed')
        self.assertEqual(diagnostic['http_status'], 403)
        self.assertTrue(diagnostic['edge_challenge'])
        self.assertEqual(diagnostic['stage'], 'preflight')
        self.assertNotIn('private', json.dumps(diagnostic))

    def test_transport_failure_is_retained_without_exception_text(self):
        for kind in (httpx.ConnectError, httpx.ReadTimeout):
            with self.subTest(kind=kind):
                def handler(request):
                    raise kind('private host and account path', request=request)
                with self.assertRaises(kind):
                    self.run_probe(handler)
                diagnostic = self.diagnostic()
                self.assertEqual(diagnostic['failure_kind'], kind.__name__)
                self.assertIsNone(diagnostic['http_status'])
                self.assertNotIn('private', json.dumps(diagnostic))

    def test_upload_failure_and_invalid_json_have_diagnostics(self):
        for status, body, kind in ((503, 'private upstream failure', AssertionError),
                                   (200, 'private invalid json', json.JSONDecodeError)):
            with self.subTest(status=status):
                def handler(request):
                    headers = {'access-control-allow-origin': self.origin,
                               'access-control-allow-methods': 'POST'}
                    return httpx.Response(200 if request.method == 'OPTIONS' else status,
                                          headers=headers, text=body)
                with self.assertRaises(kind):
                    self.run_probe(handler)
                diagnostic = self.diagnostic()
                self.assertEqual(diagnostic['stage'], 'upload')
                self.assertEqual(diagnostic['http_status'], status)
                self.assertEqual(diagnostic['case'], '01_us_consistent')
                self.assertNotIn('private', json.dumps(diagnostic))

    def test_success_without_cors_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, '未允许前端跨域'):
            self.run_probe(lambda request: httpx.Response(200))

    def test_failed_task_cannot_produce_success_artifact(self):
        def handler(request):
            headers = {'access-control-allow-origin': self.origin, 'access-control-allow-methods': 'GET, POST'}
            if request.method == 'OPTIONS':
                return httpx.Response(200, headers=headers)
            if request.method == 'POST':
                return httpx.Response(201, headers=headers, json={'task_id': 'probe'})
            return httpx.Response(200, headers=headers, json={
                'status': 'PARTIAL', 'errors': [{'code': 'DOC_PARSE_FAILED', 'level': 'ERROR',
                                                'file_ids': ['f1'], 'message': 'private detail'}],
                'documents': [{'file_id': 'f1', 'process_status': 'FAILED', 'file_name': 'private.png'},
                              {'file_id': 'f2', 'process_status': 'EXTRACTED'}],
                'extractions': [{'parse_method': 'OCR', 'text': 'private document text'}],
            })

        with self.assertRaisesRegex(AssertionError, '任务未完成'):
            self.run_probe(handler)
        self.assertFalse((self.output / '01_us_consistent.json').exists())
        diagnostic = json.loads((self.output / '01_us_consistent.diagnostic.json').read_text(encoding='utf-8'))
        self.assertEqual(diagnostic['status'], 'PARTIAL')
        self.assertEqual(diagnostic['task_id'], 'probe')
        self.assertEqual(diagnostic['error_codes'], ['DOC_PARSE_FAILED'])
        self.assertEqual(diagnostic['errors'], [{'code': 'DOC_PARSE_FAILED', 'level': 'ERROR', 'file_ids': ['f1']}])
        self.assertEqual(diagnostic['documents'][0], {'file_id': 'f1', 'process_status': 'FAILED'})
        self.assertNotIn('private', json.dumps(diagnostic))
        self.assertEqual(self.diagnostic()['stage'], 'verify_task')

    def test_poll_timeout_keeps_last_task_and_failure_stage(self):
        def handler(request):
            headers = {'access-control-allow-origin': self.origin, 'access-control-allow-methods': 'POST'}
            payload = {'task_id': 'probe'} if request.method == 'POST' else {'status': 'PROCESSING'}
            return httpx.Response(200, headers=headers, json=payload)
        with patch('smoke.time.monotonic', side_effect=[0, 91]):
            with self.assertRaisesRegex(AssertionError, '任务轮询超时'):
                self.run_probe(handler)
        self.assertEqual(self.diagnostic()['task_id'], 'probe')
        self.assertEqual(self.diagnostic()['stage'], 'poll')
        task = json.loads((self.output / '01_us_consistent.diagnostic.json').read_text(encoding='utf-8'))
        self.assertEqual(task['status'], 'PROCESSING')

    def test_scan_uploads_have_images_and_no_pdf_text_layer(self):
        from pypdf import PdfReader
        from PIL import Image
        uploads = smoke.ocr_uploads(scan=True)
        self.assertEqual(len(uploads), 3)
        sources = sorted(Path('backend/samples/11_de_multiitem_mixed').glob('*.png'))
        for (_, (name, data, mime)), source in zip(uploads, sources):
            self.assertTrue(name.endswith('.pdf'))
            self.assertEqual(mime, 'application/pdf')
            reader = PdfReader(BytesIO(data))
            self.assertEqual(len(reader.pages), 1)
            self.assertFalse(reader.pages[0].extract_text())
            self.assertTrue(reader.pages[0].images)
            with Image.open(source) as original:
                embedded = reader.pages[0].images[0].image.convert('RGB')
                self.assertTrue(embedded.tobytes() == original.convert('RGB').tobytes(),
                                '扫描探针不得通过有损压缩改变样例内容')

    def ocr_handler(self, parse_method='OCR'):
        uploads = []
        def handler(request):
            headers = {'access-control-allow-origin': self.origin, 'access-control-allow-methods': 'GET, POST'}
            if request.url.path == '/':
                return httpx.Response(200, text='<div id="app"></div><script src="/assets/app.js"></script>')
            if request.url.path == '/assets/app.js':
                return httpx.Response(200, headers={'content-type': 'application/javascript'}, text='export {}')
            if request.method == 'OPTIONS':
                return httpx.Response(200, headers=headers)
            if request.method == 'POST':
                uploads.append(request.read())
                return httpx.Response(200, headers=headers, json={'task_id': f'probe_{len(uploads)}'})
            if request.url.path.endswith('tsk_missing_deployment_probe'):
                return httpx.Response(404, json={'error': {'code': 'TASK_NOT_FOUND'}})
            if request.url.path.endswith('evaluation/latest'):
                return httpx.Response(200, headers=headers, json={'status': 'NOT_RUN'})
            task = {'status': 'COMPLETED', 'summary': {'conflict_count': 0 if len(uploads) == 1 else 1},
                    'items': [{}, {}, {}, {}],
                    'documents': [{'process_status': 'EXTRACTED'} for _ in range(3)],
                    'extractions': [{'parse_method': parse_method} for _ in range(3)],
                    'comparisons': [{'field_key': 'description', 'item_id': 'item_4', 'status': 'CONFLICT'}]}
            return httpx.Response(200, headers=headers, json=task)
        return handler, uploads

    def test_enabled_ocr_uploads_png_and_scans_and_saves_both_results(self):
        handler, uploads = self.ocr_handler()
        self.run_probe(handler, ocr_enabled=True)
        self.assertEqual(len(uploads), 5)
        self.assertIn(b'image/png', uploads[3])
        self.assertIn(b'application/pdf', uploads[4])
        self.assertTrue((self.output / 'ocr_png.json').is_file())
        self.assertTrue((self.output / 'ocr_scan.json').is_file())
        self.assertEqual(self.diagnostic()['outcome'], 'passed')

    def test_ocr_probe_rejects_a_result_that_did_not_use_ocr(self):
        handler, _ = self.ocr_handler(parse_method='TEXT_LAYER')
        with self.assertRaisesRegex(AssertionError, 'OCR'):
            self.run_probe(handler, ocr_enabled=True)
        self.assertFalse((self.output / 'ocr_png.json').exists())
        self.assertEqual(self.diagnostic()['case'], 'ocr_png')
        self.assertEqual(self.diagnostic()['outcome'], 'failed')

    def test_disabled_ocr_only_uploads_text_fixtures(self):
        handler, uploads = self.ocr_handler()
        self.run_probe(handler)
        self.assertEqual(len(uploads), 3)

    def test_frontend_missing_asset_or_html_fallback_fails_deployment(self):
        for status, content_type in ((404, 'text/plain'), (200, 'text/html')):
            with self.subTest(status=status, content_type=content_type):
                def handler(request):
                    if request.url.path == '/':
                        return httpx.Response(200, text='<div id="app"></div><script src="/assets/app.js"></script>')
                    return httpx.Response(status, headers={'content-type': content_type})
                with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                    with self.assertRaisesRegex(AssertionError, '前端资源不可用'):
                        smoke.verify_frontend(client, self.origin)

    def test_frontend_accepts_vite_relative_script_and_stylesheet(self):
        paths = []
        def handler(request):
            paths.append(request.url.path)
            if request.url.path == '/':
                return httpx.Response(200, text='<div id="app"></div><script src="./assets/app.js"></script><link href="./assets/app.css">')
            content_type = 'application/javascript' if request.url.path.endswith('.js') else 'text/css'
            return httpx.Response(200, headers={'content-type': content_type})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            smoke.verify_frontend(client, self.origin)
        self.assertEqual(paths, ['/', '/assets/app.js', '/assets/app.css'])


if __name__ == '__main__':
    unittest.main()
