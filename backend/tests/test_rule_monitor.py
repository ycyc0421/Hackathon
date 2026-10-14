import hashlib
import json
import tempfile
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import crawl_rule_sources as crawler
from app import rule_sources


class Response:
    def __init__(self, body=b'official source', content_type='text/html'):
        self.body = body
        self.url = 'https://www.fda.gov/test'
        self.headers = Message()
        self.headers['Content-Type'] = content_type
        self.headers['ETag'] = '"v1"'
    def read(self, size): return self.body[:size]
    def __enter__(self): return self
    def __exit__(self, *args): pass


class RuleMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.source = {'source_id':'test', 'url':'https://www.fda.gov/test'}
        opener_patch = patch.object(crawler, 'build_opener')
        self.addCleanup(opener_patch.stop)
        self.opener = opener_patch.start().return_value
    def tearDown(self):
        self.temp.cleanup()
    def fetch(self, raw=b'official source', previous=None):
        self.opener.open.side_effect = None
        self.opener.open.return_value = Response(raw)
        return crawler.fetch_source(self.source,self.output,previous)

    def test_304_reuses_verified_snapshot_and_validators(self):
        old = self.fetch()
        self.opener.open.side_effect = HTTPError(self.source['url'],304,'Not Modified',{},None)
        new = crawler.fetch_source(self.source,self.output,old)
        self.assertEqual(new['status'],'NOT_MODIFIED')
        self.assertEqual(new['sha256'],old['sha256'])
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.get_header('If-none-match'),'"v1"')

    def test_failure_retains_last_good_version(self):
        old=self.fetch()
        self.opener.open.side_effect=TimeoutError('temporarily unavailable')
        new=crawler.fetch_source(self.source,self.output,old)
        self.assertEqual(new['status'],'FETCH_FAILED')
        self.assertEqual(new['snapshot'],old['snapshot'])
        self.assertEqual(new['consecutive_failures'],1)
        self.assertTrue(crawler._snapshot_exists(new,self.output))

    def test_official_fallback_and_retry_preferred_resource(self):
        source={**self.source,'fallback_urls':['https://publications.europa.eu/resource/test']}
        response=Response()
        response.url=source['fallback_urls'][0]
        self.opener.open.side_effect=[ValueError('challenge'),response]
        old=crawler.fetch_source(source,self.output)
        self.assertEqual(old['retrieval_url'],response.url)
        self.opener.open.side_effect=None
        self.opener.open.return_value=response
        crawler.fetch_source(source,self.output,old)
        self.assertEqual(self.opener.open.call_args.args[0].full_url,response.url)

    def test_changed_content_queues_review_without_legal_activation(self):
        catalog={'sources':[self.source]}
        self.opener.open.return_value=Response(b'old')
        crawler.check_sources(catalog,self.output)
        self.opener.open.return_value=Response(b'new')
        crawler.check_sources(catalog,self.output)
        crawler.check_sources(catalog,self.output)
        updates=json.loads((self.output/'pending_review.json').read_text())['updates']
        self.assertEqual(len(updates),1)
        self.assertEqual(updates[0]['status'],'PENDING_REVIEW')
        self.assertTrue((self.output/updates[0]['old_snapshot']).exists())
        self.assertTrue((self.output/updates[0]['new_snapshot']).exists())
        manifest=json.loads((self.output/'manifest.json').read_text())
        self.assertFalse(manifest['automatic_activation'])
        self.assertFalse(manifest['sources'][0]['legal_verified'])
        self.assertEqual(len((self.output/'history.jsonl').read_text().splitlines()),3)

    def test_missing_snapshot_does_not_send_conditional_request(self):
        old=self.fetch()
        (self.output/old['snapshot']).unlink()
        self.fetch(previous=old)
        self.assertIsNone(self.opener.open.call_args.args[0].get_header('If-none-match'))

    def test_pdf_identity_mismatch_rejected(self):
        self.opener.open.return_value=Response(b'%PDF-fake','application/pdf')
        with patch('pypdf.PdfReader') as reader:
            reader.return_value.pages[0].extract_text.return_value='unrelated publication'
            source={**self.source,'accept':'application/pdf','expected_pdf_text':['84/500/EEC']}
            record=crawler.fetch_source(source,self.output)
            self.assertEqual(record['status'],'FETCH_FAILED')
            self.assertIn('identity',record['error'])

    def test_pdf_challenge_and_oversize_rejected(self):
        for raw in (b'not a pdf',b'%PDF- fake'):
            self.opener.open.return_value=Response(raw)
            record=crawler.fetch_source({**self.source,'accept':'application/pdf'},self.output)
            self.assertEqual(record['status'],'FETCH_FAILED')
        self.opener.open.return_value=Response(b'x'*(crawler.MAX_BYTES+1))
        self.assertEqual(crawler.fetch_source(self.source,self.output)['status'],'FETCH_FAILED')

    def test_untrusted_fallback_and_redirect_rejected(self):
        with self.assertRaises(ValueError):
            crawler.fetch_source({**self.source,'fallback_urls':['https://example.com/test']},self.output)
        with self.assertRaises(ValueError):
            crawler.OfficialRedirectHandler().redirect_request(None,None,302,'',{},'http://www.fda.gov/test')

    def test_cellar_identifier_redirect_fetched_only_over_https(self):
        req=Request('https://publications.europa.eu/resource/celex/example')
        redirected=crawler.OfficialRedirectHandler().redirect_request(req,None,303,'',{},'http://publications.europa.eu/resource/cellar/example/DOC_1')
        self.assertEqual(redirected.full_url,'https://publications.europa.eu/resource/cellar/example/DOC_1')

    def test_api_metadata_distinguishes_live_and_static_and_exposes_review_queue(self):
        self.opener.open.return_value=Response(b'old')
        crawler.check_sources({'sources':[self.source]},self.output)
        self.opener.open.return_value=Response(b'new')
        crawler.check_sources({'sources':[self.source]},self.output)
        with patch.dict('os.environ',{'RULE_SOURCE_DIR':str(self.output)}):
            status=rule_sources.status()
            self.assertEqual(status['mode'],'runtime_monitor')
            self.assertEqual(len(status['pending_updates']),1)
            self.assertFalse(status['automatic_activation'])


if __name__=='__main__': unittest.main()
