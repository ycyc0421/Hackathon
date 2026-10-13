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
from app.workflow import CorrectionRequest, WorkflowError, correct, payload_hash, report, report_html
from app.models import CheckTask
ROOT = Path(__file__).resolve().parents[2]

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'backend/.out').mkdir(parents=True,exist_ok=True)
        self.tmp = TemporaryDirectory(dir=ROOT/'backend/.out')
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
    def test_report_escapes_and_retains_failure(self):
        self.store.update(self.id,{'status':'PARTIAL','input':{**self.task['input'],'notes':'<script>alert(1)</script>'}})
        envelope = report(self.store,self.id)
        self.assertEqual(envelope['task']['status'],'PARTIAL')
        rendered = report_html(envelope)
        self.assertNotIn('<script>',rendered)
        self.assertIn('&lt;script&gt;',rendered)
    def test_running_not_editable_or_exportable(self):
        self.store.update(self.id,{'status':'PROCESSING'})
        with self.assertRaises(WorkflowError): report(self.store,self.id)
        fresh = self.store.get(self.id)
        with self.assertRaises(WorkflowError): correct(self.store,self.id,self.request(source_hash=payload_hash(fresh)))

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
            self.assertEqual(result.status_code,200)
            self.assertIn('attachment;',result.headers['content-disposition'])
            self.assertEqual(client.get(f'/api/v1/checks/{self.id}/report?format=pdf').status_code,400)
            sources = client.get('/api/v1/rules/sources')
            self.assertEqual(sources.status_code,200)
            self.assertFalse(sources.json()['automatic_activation'])
            client.close()

if __name__=='__main__': unittest.main()
