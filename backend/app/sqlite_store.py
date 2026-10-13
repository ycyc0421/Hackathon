"""C's relational tables plus lossless API payloads, committed together."""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
from tempfile import NamedTemporaryFile
from .config import DATA_DIR, TASK_DIR

DATA_ROOT = Path(__file__).resolve().parents[2] / 'data'
spec = importlib.util.spec_from_file_location('task_data_importer', DATA_ROOT / 'seed_data.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)

class TaskStore:
    def __init__(self, db_path=None, legacy_dir=None):
        self.db_path = Path(db_path or os.getenv('TASK_DB_PATH') or DATA_DIR / 'tasks.sqlite3')
        self.legacy_dir = Path(legacy_dir if legacy_dir is not None else TASK_DIR)
        self._lock = threading.RLock()
        self._seq = 0
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version != 1 and (version != 0 or tables):
                raise RuntimeError(f'数据库结构版本不兼容：{version}；请先备份，原库保持不变')
            conn.executescript((DATA_ROOT / 'schema.sql').read_text(encoding='utf-8'))
            importer.backfill_task_relations(conn)
            conn.execute('CREATE TABLE IF NOT EXISTS api_task_payloads (task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE, payload_json TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS correction_audits (source_id TEXT NOT NULL, request_id TEXT NOT NULL, derived_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id) DEFERRABLE INITIALLY DEFERRED, request_hash TEXT NOT NULL, audit_json TEXT NOT NULL, PRIMARY KEY(source_id,request_id))')

    def correction_history(self, task_id):
        with self._lock, self._connect() as conn:
            result, seen = [], set()
            current = task_id
            while current not in seen:
                seen.add(current)
                row = conn.execute('SELECT audit_json,source_id FROM correction_audits WHERE derived_id=?', (current,)).fetchone()
                if not row:
                    break
                result.append(json.loads(row[0]))
                current = row[1]
            return list(reversed(result))

    def derive(self, source_id, source_hash, request_id, request_hash, build):
        """Idempotency, source check, child payload and audit share one transaction."""
        from .workflow import payload_hash, WorkflowError
        with self._lock, self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT derived_id,request_hash FROM correction_audits WHERE source_id=? AND request_id=?', (source_id,request_id)).fetchone()
            if row:
                if row[1] != request_hash:
                    raise WorkflowError(409, 'IDEMPOTENCY_CONFLICT', 'request_id 已用于不同修正')
                return self._payload(conn, row[0])
            source = self._payload(conn, source_id)
            if source is None:
                raise WorkflowError(404, 'TASK_NOT_FOUND', '源任务不存在')
            if payload_hash(source) != source_hash:
                raise WorkflowError(409, 'SOURCE_CHANGED', '源结果已变化，请重新读取')
            task, audit = build(source)
            conn.execute('INSERT INTO correction_audits VALUES (?,?,?,?,?)', (source_id,request_id,task['task_id'],request_hash,json.dumps(audit,ensure_ascii=False,allow_nan=False)))
            # The importer commits its connection context, including the deferred audit.
            self._write(conn, task)
            return task

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute('PRAGMA foreign_keys=ON')
        return closing(conn)

    @staticmethod
    def _payload(conn, task_id):
        row = conn.execute('SELECT payload_json FROM api_task_payloads WHERE task_id=?', (task_id,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _write(conn, task):
        importer.import_task(conn, task, payload_json=json.dumps(task, ensure_ascii=False, allow_nan=False))

    def get(self, task_id):
        with self._lock, self._connect() as conn:
            task = self._payload(conn, task_id)
        if task is not None:
            return task
        if task_id.startswith('tsk_') and all(c.isalnum() or c == '_' for c in task_id):
            path = self.legacy_dir / f'{task_id}.json'
            if path.is_file():
                task = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(task, dict) or task.get('task_id') != task_id:
                    raise ValueError(f'旧任务文件 ID 不匹配：{path.name}')
                self.import_legacy(task)
                with self._connect() as conn:
                    return self._payload(conn, task_id)
        return None

    def next_seq(self):
        with self._lock:
            self._seq += 1
            return self._seq

    def create(self, task):
        with self._lock, self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM tasks WHERE task_id=?', (task['task_id'],)).fetchone():
                raise ValueError('任务 ID 已存在，拒绝覆盖')
            self._write(conn, task)

    def update(self, task_id, patch):
        with self._lock, self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task = self._payload(conn, task_id)
            if task is None:
                return
            if 'task_id' in patch and patch['task_id'] != task_id:
                raise ValueError('不能修改任务 ID')
            task.update(patch)
            self._write(conn, task)

    def persist(self, task_id):
        # Retain terminal JSON exports so an older release can read results after rollback.
        with self._lock:
            task = self.get(task_id)
            if task is None:
                return
            if not task_id.startswith('tsk_') or not all(c.isalnum() or c == '_' for c in task_id):
                raise ValueError('非法任务 ID')
            self.legacy_dir.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.legacy_dir, delete=False) as handle:
                    temporary = Path(handle.name)
                    json.dump(task, handle, ensure_ascii=False, allow_nan=False, indent=2)
                temporary.replace(self.legacy_dir / f'{task_id}.json')
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def import_legacy(self, task):
        with self._lock, self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM tasks WHERE task_id=?', (task['task_id'],)).fetchone():
                return False
            self._write(conn, task)
            return True

    def migrate_legacy(self):
        count = 0
        for path in sorted(self.legacy_dir.glob('tsk_*.json')):
            task = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(task, dict) or task.get('task_id') != path.stem:
                raise ValueError(f'旧任务文件 ID 不匹配：{path.name}')
            count += self.import_legacy(task)
        return count

    def recover_interrupted(self):
        from .util import now_iso
        with self._connect() as conn:
            ids = [row[0] for row in conn.execute("SELECT task_id FROM tasks WHERE status IN ('PENDING','PROCESSING')")]
        for task_id in ids:
            task = self.get(task_id)
            if task is not None:
                documents = task.get('documents', [])
                for document in documents:
                    if document.get('process_status') in {'UPLOADED', 'PARSING'}:
                        document.update(process_status='FAILED', error_message='服务重启中断了处理，此文件未完成解析')
                self.update(task_id, {'status': 'FAILED', 'documents': documents,
                                     'summary': {**task['summary'], 'document_count': len(documents)},
                                     'finished_at': now_iso(), 'errors': task.get('errors', []) + [
                    {'code': 'TASK_INTERRUPTED', 'message': '服务重启中断了任务，请重新上传文件', 'level': 'FATAL', 'file_ids': []}]})
                self.persist(task_id)
        return len(ids)
