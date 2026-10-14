"""Correction atomicity, source evidence and escaped report regression."""
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.sqlite_store import TaskStore
from app.workflow import CorrectionRequest, WorkflowError, correct, payload_hash, report
from app.models import CheckTask
ROOT = Path(__file__).resolve().parents[2]

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = TaskStore(Path(self.tmp.name)/'tasks.db',Path(self.tmp.name)/'legacy')
        self.task = json.loads((ROOT/'docs/fixtures/result/check-completed.json').read_text(encoding='utf-8'))
        self.task.pop('_comment',None)
        self.task['items'],self.task['comparisons'],self.task['risks'],self.task['errors'] = [],[],[],[]
        for e in self.task['extractions']:
            e['line_items'] = []
            e['fields'] = [f for f in e['fields'] if f['field_key']=='packages']
            for f in e['fields']:
                f.pop('item_id',None)
                f.pop('line_no',None)
        self.task['summary'].update(item_count=0,field_count=sum(len(e['fields']) for e in self.task['extractions']),conflict_count=0,missing_count=0,risk_count=0,unrecognized_count=0)
        self.task = CheckTask.model_validate(self.task).model_dump(mode='json')
        self.store.create(self.task)
        self.id = self.task['task_id']
    def tearDown(self): self.tmp.cleanup()
    def with_rows(self):
        from app.pipeline.rows import _field
        from app.schema_fields import ITEM_LEVEL_BY_KEY
        from app.pipeline.normalize import normalize_description
        task = copy.deepcopy(self.task)
        for extraction in task['extractions'][:2]:
            extraction['line_items'] = [{'item_no':1,'raw_text':'saved original row','fields':[
                _field(ITEM_LEVEL_BY_KEY['item_code'],'EXTRACTED','SKU-1','SKU-1'),
                _field(ITEM_LEVEL_BY_KEY['description'],'EXTRACTED','CERAMIC BOWL BLUE',normalize_description('CERAMIC BOWL BLUE')),
                _field(ITEM_LEVEL_BY_KEY['quantity'],'EXTRACTED','10 PCS',10,unit='PCS'),
                _field(ITEM_LEVEL_BY_KEY['unit_price'],'EXTRACTED','2.00',2,unit='USD'),
                _field(ITEM_LEVEL_BY_KEY['amount'],'EXTRACTED','20.00',20,unit='USD')]}]
        task['summary']['field_count'] = sum(len(e['fields']) + sum(len(row['fields']) for row in e['line_items']) for e in task['extractions'])
        return task

    def test_unrelated_corrections_keep_ocr_pending_until_description_review(self):
        from app.pipeline.align import align_items
        from app.pipeline.compare import build_item_comparisons
        task = self.with_rows()
        file_id = task['extractions'][0]['file_id']
        task['items'] = align_items(task['extractions'], task['documents'])
        task['comparisons'] = build_item_comparisons(task['items'],task['documents'],task['extractions'],lambda *_:False,
                                                   unchecked_descriptions={(file_id,1)})
        task['errors'] = [{'code':'OCR_TEXT_DISAGREEMENT','level':'WARNING','message':'saved mismatch','file_ids':[file_id]}]
        self.store.update(self.id, task)
        child = correct(self.store,self.id,self.request(source_hash=payload_hash(task)))
        description = next(c for c in child['comparisons'] if c.get('item_id') and c['field_key']=='description')
        self.assertEqual(description['status'],'NOT_CHECKED')
        field = next(f for f in child['extractions'][0]['line_items'][0]['fields'] if f['field_key']=='description')
        self.assertEqual(field['status'],'EXTRACTED')
        grandchild = correct(self.store,child['task_id'],self.request(source_hash=payload_hash(child),request_id='review-description',
            changes=[dict(file_id=file_id,item_no=1,field_key='description',value='CERAMIC BOWL BLUE')]))
        description = next(c for c in grandchild['comparisons'] if c.get('item_id') and c['field_key']=='description')
        self.assertEqual(description['status'],'MATCH')
        self.assertFalse(any(e['code']=='OCR_TEXT_DISAGREEMENT' for e in grandchild['errors']))
        self.assertEqual(self.store.get(self.id),task)

    def test_internal_arithmetic_recomputed_after_human_changes(self):
        task = self.with_rows()
        file_id = task['extractions'][0]['file_id']
        self.store.update(self.id,task)
        child = correct(self.store,self.id,self.request(source_hash=payload_hash(task),
            changes=[dict(file_id=file_id,item_no=1,field_key='amount',value='30')]))
        self.assertTrue(any(e['code']=='LINE_AMOUNT_MISMATCH' for e in child['errors']))
        grandchild = correct(self.store,child['task_id'],self.request(source_hash=payload_hash(child),request_id='fix-quantity',
            changes=[dict(file_id=file_id,item_no=1,field_key='quantity',value='15 PCS')]))
        self.assertFalse(any(e['code']=='LINE_AMOUNT_MISMATCH' for e in grandchild['errors']))
        self.assertEqual(next(f for f in grandchild['extractions'][0]['line_items'][0]['fields'] if f['field_key']=='quantity')['raw_value'],'10 PCS')
    def request(self,**kwargs):
        value = dict(request_id='edit1',source_hash=payload_hash(self.task),reason='核对原件',changes=[dict(file_id=self.task['extractions'][0]['file_id'],field_key='packages',value='121 CARTONS')])
        value.update(kwargs)
        return CorrectionRequest(**value)
    def test_preserves_evidence_recomputes_and_idempotency(self):
        child = correct(self.store,self.id,self.request())
        CheckTask.model_validate(child)
        self.assertEqual(self.store.get(self.id),self.task)
        field = next(f for f in child['extractions'][0]['fields'] if f['field_key']=='packages')
        old = next(f for f in self.task['extractions'][0]['fields'] if f['field_key']=='packages')
        self.assertEqual(field['normalized_value'],121)
        self.assertEqual(field['status'],'LOW_CONFIDENCE')
        for key in ('raw_value','raw_text','confidence','page','bbox'): self.assertEqual(field.get(key),old.get(key))
        self.assertTrue(any(c['field_key']=='packages' and c['status']=='CONFLICT' for c in child['comparisons']))
        self.assertEqual(correct(self.store,self.id,self.request()),child)
        reopened = TaskStore(self.store.db_path,self.store.legacy_dir)
        self.assertEqual(len(reopened.correction_history(child['task_id'])),1)
    def test_source_and_idempotency_conflict(self):
        with self.assertRaises(WorkflowError): correct(self.store,self.id,self.request(source_hash='0'*64))
        correct(self.store,self.id,self.request())
        with self.assertRaises(WorkflowError): correct(self.store,self.id,self.request(reason='不同原因'))
    def test_bad_batch_atomic(self):
        bad = self.request().model_dump()
        bad['changes'].append(dict(file_id='f1',field_key='gross_weight',value='不可用'))
        with self.assertRaises(WorkflowError): correct(self.store,self.id,CorrectionRequest(**bad))
        with closing(sqlite3.connect(self.store.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM correction_audits').fetchone()[0],0)
    def test_import_failure_rolls_back_audit(self):
        with patch.object(self.store,'_write',side_effect=RuntimeError('storage failed')):
            with self.assertRaises(RuntimeError): correct(self.store,self.id,self.request())
        with closing(sqlite3.connect(self.store.db_path)) as conn: self.assertEqual(conn.execute('SELECT count(*) FROM correction_audits').fetchone()[0],0)
    def test_reject_duplicate_and_uneditable(self):
        req = self.request().model_dump()
        req['changes'] *= 2
        with self.assertRaises(WorkflowError): correct(self.store,self.id,CorrectionRequest(**req))
        req['changes'] = [dict(file_id='f1',field_key='status',value='MATCH')]
        with self.assertRaises(WorkflowError): correct(self.store,self.id,CorrectionRequest(**req))
    def test_report_preserves_literal_content_and_failure(self):
        self.store.update(self.id,{'status':'PARTIAL','input':{**self.task['input'],'notes':'<script>alert(1)</script>'}})
        envelope = report(self.store,self.id)
        self.assertEqual(envelope['task']['status'],'PARTIAL')
        self.assertEqual(envelope['task']['input']['notes'], '<script>alert(1)</script>')
        self.assertNotIn('extractions', envelope['task'])
        self.assertIn('extractions', report(self.store, self.id, view='archive')['task'])

    def test_report_keeps_business_fields_without_duplicating_comparisons(self):
        from app.pipeline.compare import build_comparisons
        from app.pipeline.trade_json import parse_trade_json, FORMAT
        fields = {'document_no': 'INV-1', 'invoice_no': 'INV-1',
                  'shipper': 'EXPORTER LTD', 'consignee': 'BUYER LTD',
                  'contract_no': 'CONTRACT-1', 'container_no': 'CONT-1',
                  'port_of_loading': 'NINGBO', 'port_of_discharge': 'HAMBURG',
                  'packages': '120 CARTONS'}
        for count in (1, 2):
            with self.subTest(document_count=count):
                task = copy.deepcopy(self.task)
                task['documents'] = task['documents'][:count]
                task['extractions'] = task['extractions'][:count]
                for index, extraction in enumerate(task['extractions']):
                    values = fields if index == 0 else {'packages': '120 CARTONS', 'shipper': 'EXPORTER LTD'}
                    parsed = parse_trade_json(json.dumps({'format': FORMAT,
                        'doc_type': task['documents'][index]['doc_type'], 'fields': values}).encode())
                    extraction.update(parsed)
                task['comparisons'] = build_comparisons(task['documents'], task['extractions'], lambda *_: False)
                task['summary'].update(document_count=count, field_count=sum(len(e['fields']) for e in task['extractions']))
                self.store.update(self.id, task)
                result = report(self.store, self.id)
                document = result['documents'][0]
                remaining = {f['field_key']: f for f in document['fields']}
                expected = set(fields) - {'document_no', 'invoice_no', 'packages'}
                if count == 2:
                    expected.remove('shipper')
                    self.assertTrue(any(c['field_key'] == 'shipper' for c in result['comparisons']))
                self.assertEqual(set(remaining), expected)
                for field in task['extractions'][0]['fields']:
                    if field['field_key'] in expected:
                        self.assertEqual(remaining[field['field_key']], field)
                self.assertEqual(self.store.get(self.id), task)

    def test_report_keeps_controlled_failure_reason(self):
        from app.pipeline.reader import ReadResult
        from app.public_errors import parse_failure
        message = '未检测到文本层（疑似扫描件），且未配置识别服务'
        parsed = ReadResult(failed=True, error_message=message)
        self.assertIn('提供带文本层的 PDF', parsed.error_message)
        self.assertEqual(parse_failure(parsed.error_message), parsed.error_message)
        task = copy.deepcopy(self.task)
        task['documents'][0].update(process_status='FAILED', error_message=parsed.error_message)
        task['errors'] = [{'code': 'DOC_PARSE_FAILED', 'level': 'ERROR',
                           'message': 'scan.pdf 解析失败：' + parsed.error_message, 'file_ids': ['f1']}]
        self.store.update(self.id, task)
        for view in ('content', 'archive'):
            result = report(self.store, self.id, view=view)
            projected = result['task'] if view == 'archive' else result
            self.assertEqual(projected['documents'][0]['error_message'], parsed.error_message)
            self.assertEqual(projected['errors'][0]['message'], parsed.error_message)

    def test_image_unavailable_reason_survives_read_result(self):
        from app.pipeline import reader
        with patch.object(reader, 'PADDLE_OCR_ENABLED', False), patch.object(reader, 'llm_enabled', return_value=False):
            result = reader._read_image(b'synthetic image')
        self.assertTrue(result.failed)
        self.assertIn('提供带文本层的 PDF', result.error_message)

    def test_running_not_editable_or_exportable(self):
        self.store.update(self.id,{'status':'PROCESSING'})
        with self.assertRaises(WorkflowError): report(self.store,self.id)
        fresh = self.store.get(self.id)
        with self.assertRaises(WorkflowError): correct(self.store,self.id,self.request(source_hash=payload_hash(fresh)))

    def test_report_relevant_sources_and_unknown_history(self):
        task = copy.deepcopy(self.task)
        task['risks'] = [{'risk_id':'r1','type':'HS_CLASSIFICATION','severity':'WARNING',
                         'title':'【演示规则·未经核实】用途待核对','detail':'未取得食品用途',
                         'related_field_keys':['hs_code'],'related_file_ids':[], 'related_item_ids':[],
                         'destination_country':'DE','rule_id':'DE-CERAMICS-6911','rule_source':None}]
        task['errors'] = [{'code':'RULES_UNVERIFIED','level':'WARNING','message':'规则未核实','file_ids':[]}]
        self.store.update(self.id,task)
        result = report(self.store,self.id)
        self.assertIsNone(result['provenance']['execution_rule_version'])
        self.assertEqual(result['provenance']['execution_version_status'],'UNKNOWN')
        self.assertEqual({s['source_id'] for s in result['provenance']['sources']}, {'EU-FCM-LEGISLATION','EU-CERAMICS-84-500'})
        self.assertEqual(result['risks'][0]['rule_context']['verification_status'],'UNVERIFIED')
        self.assertEqual(result['risks'][0]['title'],'用途待核对')
        self.assertEqual(result['provenance']['rule_verification_status'],'UNVERIFIED')
        self.assertEqual(result['errors'],[])
        self.assertEqual(report(self.store,self.id,view='archive')['task']['risks'],task['risks'])
        self.assertEqual(result['result_hash'],payload_hash(self.store.get(self.id)))

    def test_diagnostics_stay_out_of_public_reports(self):
        from app.pipeline.reader import ReadResult
        diagnostic='PDF 第 2 页：backend exploded /private/path?token=secret .env LLM_API_KEY'
        parsed=ReadResult(failed=True,error_message=diagnostic)
        self.assertIn('第 2 页',parsed.error_message)
        self.assertNotIn('secret',parsed.error_message)
        task=copy.deepcopy(self.task)
        task['documents'][0].update(process_status='FAILED',error_message=diagnostic)
        task['errors']=[{'code':'DOC_PARSE_FAILED','message':diagnostic,'level':'ERROR','file_ids':['f1']}]
        self.store.update(self.id,task)
        for view in ('content','archive'):
            result=report(self.store,self.id,view=view)
            self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(self.store.get(self.id)['documents'][0]['error_message'],diagnostic)

    def test_source_projection_excludes_operations(self):
        from app import rule_sources
        root=Path(self.tmp.name)
        (root/'manifest.json').write_text(json.dumps({'sources':[{'source_id':'S1','status':'FETCH_FAILED',
            'url':'https://example.test/reference','error':'token=secret','snapshot':'/private/path',
            'attempts':[{'url':'private'}],'etag':'private'}]}))
        (root/'pending_review.json').write_text(json.dumps({'updates':[{'source_id':'S1','status':'PENDING_REVIEW',
            'old_snapshot':'private','error':'secret','checked_at':'2026-10-13'}]}))
        with patch.dict(os.environ,{'RULE_SOURCE_DIR':str(root)}):
            result=rule_sources.status()
            self.assertEqual(result['sources'][0]['status'],'FETCH_FAILED')
            self.assertEqual(result['pending_updates'][0]['source_id'],'S1')
            self.assertNotIn('private',json.dumps(result))
            self.assertNotIn('secret',json.dumps(result))

    def test_report_preserves_conclusions_without_guessing_evidence(self):
        child = correct(self.store,self.id,self.request())
        extraction = child['extractions'][0]
        extraction['fields'].append(copy.deepcopy(extraction['fields'][0]))
        self.store.update(child['task_id'],child)
        result = report(self.store,child['task_id'])
        self.assertEqual([(c['status'],c['note']) for c in result['comparisons']],
                         [(c['status'],c['note']) for c in child['comparisons']])
        self.assertEqual(result['task']['summary'],child['summary'])
        value = next(v for c in result['comparisons'] if c['field_key']=='packages'
                     for v in c['values'] if v['file_id']==extraction['file_id'])
        self.assertEqual(value['evidence']['status'],'UNAVAILABLE')
        self.assertIsNone(value['evidence']['raw_text'])

    def test_item_revision_real_conflict_and_audit_chain(self):
        from app.pipeline.rows import _field
        from app.schema_fields import ITEM_LEVEL_BY_KEY
        revised = copy.deepcopy(self.task)
        for extraction in revised['extractions'][:2]:
            extraction['line_items'] = [{'item_no':1,'raw_text':'original table row','fields':[
                _field(ITEM_LEVEL_BY_KEY['item_code'],'EXTRACTED','SKU-1','SKU-1'),
                _field(ITEM_LEVEL_BY_KEY['description'],'EXTRACTED','CERAMIC BOWL BLUE','陶瓷 碗 蓝')]}]
        self.store.update(self.id,revised)
        request = self.request(source_hash=payload_hash(revised),changes=[dict(file_id=revised['extractions'][0]['file_id'],item_no=1,field_key='description',value='CERAMIC BOWL BEIGE')])
        child = correct(self.store,self.id,request)
        self.assertTrue(any(c['scope']=='ITEM' and c['field_key']=='description' and c['status']=='CONFLICT' for c in child['comparisons']))
        grandchild = correct(self.store,child['task_id'],self.request(source_hash=payload_hash(child),request_id='edit2'))
        self.assertEqual(len(self.store.correction_history(grandchild['task_id'])),2)

    @unittest.skipIf(os.name=='nt','Windows sandbox TestClient transport hangs; execute HTTP integration on Linux')
    def test_http_contract_and_unsupported_export(self):
        from app import main
        from fastapi.testclient import TestClient
        with patch.object(main,'store',self.store):
            client = TestClient(main.app)
            result = client.get(f'/api/v1/checks/{self.id}/corrections')
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['result_hash'],payload_hash(self.task))
            result = client.post(f'/api/v1/checks/{self.id}/corrections',json=self.request().model_dump())
            self.assertEqual(result.status_code,200)
            result = client.get(f'/api/v1/checks/{self.id}/report?format=html')
            self.assertEqual(result.status_code,410)
            result = client.get(f'/api/v1/checks/{self.id}/report?view=archive')
            self.assertEqual(result.status_code,200)
            self.assertIn('attachment;',result.headers['content-disposition'])
            self.assertEqual(client.get(f'/api/v1/checks/{self.id}/report?format=pdf').status_code,400)
            sources = client.get('/api/v1/rules/sources')
            self.assertEqual(sources.status_code,200)
            self.assertFalse(sources.json()['automatic_activation'])
            client.close()

if __name__=='__main__': unittest.main()
