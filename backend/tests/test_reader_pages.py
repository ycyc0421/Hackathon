"""Controlled HTTP model responses verify page boundaries without external calls."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.pipeline import reader
from app.pipeline.runner import _locate_document_pages
from app.pipeline.rows import TableResult
from app.pipeline.extract import extract_fields


class PageTranscriptionTests(unittest.TestCase):
    def test_unique_document_evidence_gets_page_repeated_value_remains_unknown(self):
        texts = ['COMMERCIAL INVOICE\nDocument No.: CI-PAGE-1\nCurrency: USD',
                 'TOTAL AMOUNT (USD): 1400.00\nCurrency: USD']
        fields=extract_fields('\n'.join(texts),'COMMERCIAL_INVOICE')
        tables=[TableResult([],text,set(),False,False) for text in texts]
        _locate_document_pages(fields,tables,'COMMERCIAL_INVOICE')
        fields={field['field_key']:field for field in fields}
        self.assertEqual(fields['document_no']['page'],1)
        self.assertEqual(fields['total_amount']['page'],2)
        self.assertIsNone(fields['currency']['page'])

    def response(self, text):
        return httpx.Response(200,request=httpx.Request('POST','https://model.example/chat/completions'),
                              json={'choices':[{'message':{'content':text}}]})

    def test_separate_pages_are_not_merged_by_the_model(self):
        pages = ['COMMERCIAL INVOICE\nNO.   SKU   DESCRIPTION   QTY\n1   A1   MUG   20 PCS\nTOTAL: 20 PCS',
                 'COMMERCIAL INVOICE\nNO.   SKU   DESCRIPTION   QTY\n1   B2   BOWL   30 PCS\nTOTAL: 30 PCS']
        with patch('httpx.post',side_effect=[self.response(text) for text in pages]) as post:
            result = reader._transcribe_with_llm([('image/png',b'page1'),('image/png',b'page2')],page_count=2)
        self.assertTrue(result.ok,result.error_message)
        self.assertEqual(result.page_texts,pages)
        self.assertEqual(result.page_count,2)
        self.assertEqual(post.call_count,2)
        for call in post.call_args_list:
            self.assertEqual(len(call.kwargs['json']['messages'][0]['content']),2)

    def test_page_failure_does_not_publish_partial_transcription_as_success(self):
        with patch('httpx.post',side_effect=[self.response('COMMERCIAL INVOICE\nDocument No. CI-12345\nTOTAL AMOUNT USD 1000.00'),
                                           self.response('')]):
            result=reader._transcribe_with_llm([('image/png',b'one'),('image/png',b'two')],page_count=2)
        self.assertTrue(result.failed)
        self.assertIn('2',result.error_message)
        self.assertEqual(result.page_texts,[])

    def test_page_count_mismatch_never_calls_external_model(self):
        with patch('httpx.post') as post:
            result=reader._transcribe_with_llm([('image/png',b'one')],page_count=2)
        self.assertTrue(result.failed)
        post.assert_not_called()


if __name__=='__main__': unittest.main()
