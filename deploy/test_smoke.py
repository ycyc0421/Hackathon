"""公网挑战、跨域缺失和任务失败都必须阻止发布。"""

from pathlib import Path
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

    def run_probe(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), headers={'Origin': self.origin})
        with patch('smoke.httpx.Client', return_value=client):
            smoke.run(self.base, self.origin, self.output)

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
            return httpx.Response(200, headers=headers, json={'status': 'FAILED'})

        with self.assertRaisesRegex(AssertionError, '任务未完成'):
            self.run_probe(handler)
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
