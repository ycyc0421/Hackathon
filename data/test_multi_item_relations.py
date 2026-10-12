"""多商品引用与旧库回填回归，所有写入仅进入临时数据库。"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.sqlite_store import TaskStore
from seed_data import import_task


def sample(task_id="tsk_relations"):
    return {
        "task_id": task_id, "status": "COMPLETED",
        "created_at": "2026-10-12T00:00:00+08:00", "finished_at": None,
        "input": {"destination_country": "DE"},
        "documents": [{"file_id": "f1", "file_name": "invoice.pdf", "file_type": "PDF",
                       "doc_type": "COMMERCIAL_INVOICE", "process_status": "EXTRACTED"}],
        "items": [{"item_id": f"itm_{i}", "label": f"商品 {i}",
                   "members": [{"file_id": "f1", "item_no": i}]} for i in (1, 2)],
        "extractions": [{"file_id": "f1", "parse_method": "TEXT_LAYER", "fields": [],
                         "line_items": [{"item_no": i, "fields": [{
                             "field_key": "quantity", "label": "数量", "raw_text": f"{i * 10} PCS",
                             "raw_value": str(i * 10), "normalized_value": i * 10,
                             "unit": "PCS", "confidence": 0.73, "status": "EXTRACTED",
                             "page": 1, "bbox": None,
                         }]} for i in (1, 2)]}],
        "comparisons": [], "errors": [],
        "risks": [{"risk_id": "r1", "title": "多商品风险", "detail": "需要复核",
                   "related_field_keys": ["quantity"], "related_file_ids": ["f1"],
                   "related_item_ids": ["itm_2", "itm_1"]}],
    }


class MultiItemRelationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TaskStore(self.root / "tasks.db", self.root / "legacy")
        self.task = sample()

    def tearDown(self):
        self.temp.cleanup()

    def query(self, sql, args=()):
        with closing(sqlite3.connect(self.store.db_path)) as conn:
            return conn.execute(sql, args).fetchall()

    def snapshot(self):
        with closing(sqlite3.connect(self.store.db_path)) as conn:
            return list(conn.iterdump())

    def reopen(self):
        return TaskStore(self.store.db_path, self.store.legacy_dir)

    def make_legacy_database(self):
        # 保留旧版已有任务和完整快照，移除旧导入器尚未写入的关系。
        with closing(sqlite3.connect(self.store.db_path)) as conn, conn:
            conn.execute("DELETE FROM extracted_fields WHERE line_no IS NOT NULL")
            conn.execute("DROP TABLE risk_items")
            conn.execute("DROP TABLE IF EXISTS task_relation_state")

    def test_duplicate_risk_items_preserve_order_and_payload(self):
        self.task["risks"][0]["related_item_ids"] = ["itm_2", "itm_1", "itm_2"]
        self.store.create(self.task)
        self.assertEqual(self.query("SELECT item_id,position FROM risk_items ORDER BY position"),
                         [("itm_2", 0), ("itm_1", 1)])
        self.assertEqual(self.store.get(self.task["task_id"]), self.task)

    def test_duplicate_risk_items_in_legacy_json_can_migrate(self):
        self.task["risks"][0]["related_item_ids"] = ["itm_1", "itm_1"]
        self.store.legacy_dir.mkdir()
        (self.store.legacy_dir / (self.task["task_id"] + ".json")).write_text(json.dumps(self.task))
        self.assertEqual(self.store.migrate_legacy(), 1)
        self.assertEqual(self.store.migrate_legacy(), 0)
        self.assertEqual(self.query("SELECT item_id,position FROM risk_items"), [("itm_1", 0)])

    def test_invalid_row_ownership_rolls_back(self):
        self.store.create(self.task)
        before = self.snapshot()
        for problem in ("duplicate_owner", "missing_row", "duplicate_row",
                        "field_owner", "field_line"):
            with self.subTest(problem=problem):
                task = deepcopy(self.task)
                rows = task["extractions"][0]["line_items"]
                if problem == "duplicate_owner":
                    task["items"][1]["members"][0]["item_no"] = 1
                elif problem == "missing_row":
                    task["items"][0]["members"][0]["item_no"] = 999
                elif problem == "duplicate_row":
                    rows.append(deepcopy(rows[0]))
                elif problem == "field_owner":
                    rows[0]["fields"][0]["item_id"] = "itm_2"
                else:
                    rows[0]["fields"][0]["line_no"] = 999
                with self.assertRaises(ValueError):
                    self.store.update(task["task_id"], task)
                self.assertEqual(self.snapshot(), before)

    def test_null_field_hints_do_not_erase_row_ownership(self):
        self.task["extractions"][0]["line_items"][0]["fields"][0].update(item_id=None, line_no=None)
        self.store.create(self.task)
        self.assertEqual(self.query("SELECT item_id,line_no FROM extracted_fields ORDER BY line_no"),
                         [("itm_1", 1), ("itm_2", 2)])

    def test_rows_without_item_groups_keep_unassigned_evidence(self):
        self.task["items"] = []
        self.task["risks"] = []
        self.store.create(self.task)
        self.assertEqual(self.query("SELECT item_id,line_no,raw_value FROM extracted_fields ORDER BY line_no"),
                         [(None, 1, "10"), (None, 2, "20")])
        self.assertEqual(self.store.get(self.task["task_id"]), self.task)

    def test_upgrade_backfills_without_changing_payload_or_audit(self):
        self.store.create(self.task)
        with closing(sqlite3.connect(self.store.db_path)) as conn, conn:
            conn.execute("CREATE TABLE correction_audits (derived_id TEXT REFERENCES tasks(task_id), audit_json TEXT)")
            conn.execute("INSERT INTO correction_audits VALUES (?,?)", (self.task["task_id"], "original audit"))
        payload = self.query("SELECT * FROM api_task_payloads")
        self.make_legacy_database()
        self.reopen()
        self.assertEqual(self.query("SELECT item_id,line_no,raw_text,confidence,page FROM extracted_fields ORDER BY line_no"),
                         [("itm_1", 1, "10 PCS", 0.73, 1), ("itm_2", 2, "20 PCS", 0.73, 1)])
        self.assertEqual(self.query("SELECT item_id,position FROM risk_items ORDER BY position"),
                         [("itm_2", 0), ("itm_1", 1)])
        self.assertEqual(self.query("SELECT * FROM api_task_payloads"), payload)
        self.assertEqual(self.query("SELECT * FROM correction_audits"), [(self.task["task_id"], "original audit")])
        after = self.snapshot()
        self.reopen()
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(self.query("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.query("PRAGMA user_version"), [(1,)])

    def test_upgrade_without_payload_keeps_known_scalar_relation(self):
        self.task["risks"][0].pop("related_item_ids")
        self.task["risks"][0]["item_id"] = "itm_1"
        self.store.create(self.task)
        self.make_legacy_database()
        with closing(sqlite3.connect(self.store.db_path)) as conn, conn:
            conn.execute("DELETE FROM api_task_payloads")
        self.reopen()
        self.assertEqual(self.query("SELECT item_id,position FROM risk_items"), [("itm_1", 0)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM extracted_fields"), [(0,)])

    def test_old_version_rewrite_is_backfilled_again(self):
        self.store.create(self.task)
        self.task["extractions"][0]["line_items"][0]["fields"][0]["normalized_value"] = 99
        legacy = deepcopy(self.task)
        for item in legacy["items"]:
            item.pop("members")
        legacy["extractions"][0]["line_items"] = []
        legacy["risks"][0]["related_item_ids"] = []
        with closing(sqlite3.connect(self.store.db_path)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                conn.execute("DELETE FROM tasks WHERE task_id=?", (self.task["task_id"],))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM task_relation_state").fetchone(), (0,))
            # 模拟旧版本只重写既有关系和完整快照，没有写入新关系标记。
            import_task(conn, legacy, payload_json=json.dumps(self.task))
            with conn:
                conn.execute("DELETE FROM task_relation_state")
        self.reopen()
        self.assertEqual(self.query("SELECT normalized_value_json FROM extracted_fields ORDER BY line_no"),
                         [("99",), ("20",)])
        self.assertEqual(self.query("SELECT item_id FROM risk_items ORDER BY position"),
                         [("itm_2",), ("itm_1",)])

    def test_failed_upgrade_is_atomic_and_can_retry(self):
        self.store.create(self.task)
        second = sample("tsk_second")
        self.store.create(second)
        self.make_legacy_database()
        second["items"][0]["members"][0]["item_no"] = 999
        with closing(sqlite3.connect(self.store.db_path)) as conn, conn:
            conn.execute("UPDATE api_task_payloads SET payload_json=? WHERE task_id=?",
                         (json.dumps(second), second["task_id"]))
        with self.assertRaises(ValueError):
            self.reopen()
        self.assertEqual(self.query("SELECT COUNT(*) FROM extracted_fields"), [(0,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM risk_items"), [(0,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM task_relation_state"), [(0,)])
        with closing(sqlite3.connect(self.store.db_path)) as conn, conn:
            conn.execute("UPDATE api_task_payloads SET payload_json=? WHERE task_id=?",
                         (json.dumps(sample(second["task_id"])), second["task_id"]))
        self.reopen()
        self.assertEqual(self.query("SELECT COUNT(*) FROM extracted_fields"), [(4,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM risk_items"), [(4,)])

    def test_payload_task_id_mismatch_does_not_touch_another_task(self):
        self.store.create(self.task)
        self.store.create(sample("tsk_second"))
        self.make_legacy_database()
        with closing(sqlite3.connect(self.store.db_path)) as conn, conn:
            conn.execute("UPDATE api_task_payloads SET payload_json=? WHERE task_id=?",
                         (json.dumps(sample("tsk_second")), self.task["task_id"]))
        with self.assertRaises(ValueError):
            self.reopen()
        self.assertEqual(self.query("SELECT COUNT(*) FROM extracted_fields"), [(0,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM risk_items"), [(0,)])


if __name__ == "__main__":
    unittest.main()
