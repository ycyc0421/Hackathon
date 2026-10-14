"""Durability, task isolation, migrations and atomic rollback regression."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import subprocess
import os
from tempfile import TemporaryDirectory
import unittest
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sqlite_store import TaskStore
ROOT = Path(__file__).resolve().parents[2]

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.db = self.path / 'tasks.db'
        self.legacy = self.path / 'legacy'
        self.legacy.mkdir()
        self.store = TaskStore(self.db, self.legacy)
        self.task = json.loads((ROOT / 'docs/fixtures/result/check-completed.json').read_text(encoding='utf-8'))
        self.task.pop('_comment', None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_restart_exact_payload_and_relations(self):
        self.store.create(self.task)
        self.assertEqual(TaskStore(self.db, self.legacy).get(self.task['task_id']), self.task)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(conn.execute('SELECT count(*) FROM documents').fetchone()[0], len(self.task['documents']))
            self.assertEqual(conn.execute('SELECT count(*) FROM extracted_fields').fetchone()[0], sum(len(x['fields']) for x in self.task['extractions']))

    def test_result_readable_in_another_python_process(self):
        self.store.create(self.task)
        code = 'import json,sys; from app.sqlite_store import TaskStore; print(json.dumps(TaskStore(sys.argv[1],sys.argv[2]).get(sys.argv[3])))'
        result = subprocess.run([sys.executable, '-c', code, str(self.db), str(self.legacy), self.task['task_id']],
            env={**os.environ, 'PYTHONPATH': str(ROOT / 'backend')}, capture_output=True, check=True, timeout=30)
        self.assertEqual(json.loads(result.stdout), self.task)

    def test_duplicate_and_task_local_ids(self):
        self.store.create(self.task)
        with self.assertRaises(ValueError): self.store.create(self.task)
        second = copy.deepcopy(self.task)
        second['task_id'] += '_second'
        self.store.create(second)
        self.store.update(second['task_id'], {'input': {**second['input'], 'notes': 'changed'}})
        self.assertEqual(self.store.get(self.task['task_id']), self.task)

    def test_atomic_database_failure(self):
        self.store.create(self.task)
        broken = copy.deepcopy(self.task['documents'])
        broken[0]['file_type'] = 'INVALID'
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.update(self.task['task_id'], {'documents': broken})
        self.assertEqual(self.store.get(self.task['task_id']), self.task)

    def test_terminal_json_compatible_with_old_release(self):
        self.store.create(self.task)
        self.store.persist(self.task['task_id'])
        path = self.legacy / (self.task['task_id'] + '.json')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), self.task)
        self.assertEqual(len(list(self.legacy.iterdir())), 1)

    def test_migration_idempotent_does_not_overwrite(self):
        path = self.legacy / (self.task['task_id'] + '.json')
        path.write_text(json.dumps(self.task), encoding='utf-8')
        self.assertEqual(self.store.migrate_legacy(), 1)
        self.store.update(self.task['task_id'], {'input': {**self.task['input'], 'notes': 'new'}})
        self.assertEqual(self.store.migrate_legacy(), 0)
        self.assertEqual(self.store.get(self.task['task_id'])['input']['notes'], 'new')
        self.assertTrue(path.exists())

    def test_recovery(self):
        self.task['status'] = 'PROCESSING'
        self.store.create(self.task)
        restarted = TaskStore(self.db, self.legacy)
        self.assertEqual(restarted.recover_interrupted(), 1)
        task = restarted.get(self.task['task_id'])
        self.assertEqual(task['status'], 'FAILED')
        self.assertEqual(task['errors'][-1]['code'], 'TASK_INTERRUPTED')
        self.assertEqual(restarted.recover_interrupted(), 0)

    def test_concurrent_updates_do_not_lose_independent_changes(self):
        self.store.create(self.task)
        other = TaskStore(self.db, self.legacy)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(self.store.update, self.task['task_id'], {'status': 'PARTIAL'}),
                    pool.submit(other.update, self.task['task_id'], {'finished_at': '2026-10-12T12:00:00+08:00'})]
            for job in jobs: job.result()
        task = self.store.get(self.task['task_id'])
        self.assertEqual(task['status'], 'PARTIAL')
        self.assertEqual(task['finished_at'], '2026-10-12T12:00:00+08:00')

    def test_ocr_evidence_and_item_members_preserved(self):
        rows = []
        for number, item in enumerate(self.task['items'], 1):
            item['label'] = item.pop('display_name', '陶瓷杯')
            item['alignment_status'] = 'ALIGNED'
            item['members'] = [{'file_id': self.task['documents'][0]['file_id'], 'item_no': number, 'match_score': None}]
            field = copy.deepcopy(self.task['extractions'][0]['fields'][0])
            field.update(item_id=item['item_id'], line_no=number)
            rows.append({'item_no': number, 'fields': [field]})
        self.task['extractions'][0]['line_items'] = rows
        self.task['extractions'][0]['fields'][0].update(raw_text='CERAMIC MUG 35OML', raw_value='35OML', normalized_value='350ML', status='LOW_CONFIDENCE')
        self.task['errors'].append({'code': 'OCR_AUTO_CORRECTED', 'message': '核对原件', 'level': 'WARNING', 'file_ids': [self.task['documents'][0]['file_id']]})
        self.store.create(self.task)
        self.assertEqual(TaskStore(self.db, self.legacy).get(self.task['task_id']), self.task)

    def test_unsupported_database_unchanged(self):
        other = self.path / 'other.db'
        with closing(sqlite3.connect(other)) as conn:
            conn.execute('CREATE TABLE old(value TEXT)')
        before = other.read_bytes()
        with self.assertRaises(RuntimeError): TaskStore(other, self.legacy)
        self.assertEqual(other.read_bytes(), before)

if __name__ == '__main__':
    unittest.main()
