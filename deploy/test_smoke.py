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
                'status': 'PARTIAL', 'errors': [{'code': 'OCR_UNAVAILABLE', 'message': 'private detail'}],
                'documents': [{'process_status': 'FAILED', 'filename': 'private.png'}],
                'extractions': [{'parse_method': 'OCR', 'text': 'private document text'}],
            })

        with self.assertRaisesRegex(AssertionError, '任务未完成'):
            self.run_probe(handler)
        self.assertFalse((self.output / '01_us_consistent.json').exists())
        diagnostic = json.loads((self.output / '01_us_consistent.diagnostic.json').read_text(encoding='utf-8'))
        self.assertEqual(diagnostic['status'], 'PARTIAL')
        self.assertEqual(diagnostic['task_id'], 'probe')
        self.assertEqual(diagnostic['error_codes'], ['OCR_UNAVAILABLE'])
        self.assertNotIn('private', json.dumps(diagnostic))

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

    def test_ocr_probe_rejects_a_result_that_did_not_use_ocr(self):
        handler, _ = self.ocr_handler(parse_method='TEXT_LAYER')
        with self.assertRaisesRegex(AssertionError, 'OCR'):
            self.run_probe(handler, ocr_enabled=True)
        self.assertFalse((self.output / 'ocr_png.json').exists())

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
