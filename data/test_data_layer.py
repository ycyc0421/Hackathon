"""Regression tests for the SQLite schema and JSON importer."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import init_db
from generator import build_cases
from seed_data import import_task


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / "data" / "schema.sql").read_text(encoding="utf-8")


class DataLayerTests(unittest.TestCase):
    def setUp(self):
        self.handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.handle.close()
        self.conn = sqlite3.connect(self.handle.name)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def tearDown(self):
        self.conn.close()
        Path(self.handle.name).unlink(missing_ok=True)

    def load_case(self, name):
        return next(case for case in build_cases(20261010) if case["case_id"] == name)

    def test_generated_comparisons_and_raw_values_survive_import(self):
        case = self.load_case("normal_single")
        import_task(self.conn, case)
        expected = case["expected"]["comparisons"]
        actual = self.conn.execute(
            "SELECT COUNT(*), (SELECT COUNT(*) FROM comparison_values) FROM comparisons"
        ).fetchone()
        self.assertEqual(actual, (len(expected), sum(len(c["values"]) for c in expected)))
        expected_raw = sorted((v["raw_value"] or "") for c in expected for v in c["values"])
        actual_raw = sorted((row[0] or "") for row in self.conn.execute(
            "SELECT raw_value FROM comparison_values"))
        self.assertEqual(actual_raw, expected_raw)

    def test_task_local_ids_can_be_reused_and_reimport_is_scoped(self):
        first = self.load_case("normal_single")
        second = self.load_case("quantity_conflict_single")
        import_task(self.conn, first)
        import_task(self.conn, second)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 5)
        import_task(self.conn, first)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 2)
        counts = dict(self.conn.execute(
            "SELECT task_id, COUNT(*) FROM documents GROUP BY task_id"))
        self.assertEqual(counts, {
            "generated_normal_single": 3,
            "generated_quantity_conflict_single": 2,
        })

    def test_processing_status_and_explicit_empty_items_are_preserved(self):
        source = {
            "task_id": "empty_processing",
            "status": "PROCESSING",
            "created_at": "2026-10-11T00:00:00+00:00",
            "finished_at": None,
            "input": {"destination_country": "DE"},
            "items": [], "documents": [], "extractions": [],
            "comparisons": [], "risks": [],
        }
        import_task(self.conn, source)
        self.assertEqual(self.conn.execute(
            "SELECT status FROM tasks WHERE task_id = 'empty_processing'"
        ).fetchone()[0], "PROCESSING")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM items WHERE task_id = 'empty_processing'"
        ).fetchone()[0], 0)

    def test_formal_metadata_survives_import_and_can_be_cleared(self):
        source = json.loads((ROOT / "docs/fixtures/result/check-partial.json").read_text(encoding="utf-8"))
        source["errors"].append({
            "code": "RULES_UNVERIFIED", "level": "WARNING",
            "message": "规则来源尚未核实，请人工核验。", "file_ids": [],
        })
        source["comparisons"][0]["suggested_action"] = "核对原始单证的件数记录。"
        source["risks"][0]["suggested_action"] = "核验规则来源和适用条件。"
        task_id = import_task(self.conn, source)
        errors = self.conn.execute(
            "SELECT errors_json FROM tasks WHERE task_id = ?", (task_id,),
        ).fetchone()[0]
        self.assertEqual(json.loads(errors), source["errors"])
        methods = {e["file_id"]: e.get("parse_method") for e in source["extractions"]}
        self.assertEqual({
            json.loads(file_id)[1]: method for file_id, method in self.conn.execute(
                "SELECT file_id,parse_method FROM documents WHERE task_id = ?", (task_id,),
            )
        }, {d["file_id"]: methods.get(d["file_id"]) for d in source["documents"]})
        for table, key in (("comparisons", "comparison_id"), ("risks", "risk_id")):
            self.assertEqual({
                json.loads(row_id)[1]: action for row_id, action in self.conn.execute(
                    f"SELECT {key},suggested_action FROM {table} WHERE task_id = ?", (task_id,),
                )
            }, {row[key]: row.get("suggested_action") for row in source[table]})

        # 重导时省略可选信息，应清空旧值，不得沿用上一次的建议。
        source["errors"] = []
        for extraction in source["extractions"]:
            extraction.pop("parse_method", None)
        for row in source["comparisons"] + source["risks"]:
            row.pop("suggested_action", None)
        import_task(self.conn, source)
        self.assertEqual(self.conn.execute(
            "SELECT errors_json FROM tasks WHERE task_id = ?", (task_id,),
        ).fetchone()[0], "[]")
        for table, column in (("documents", "parse_method"),
                              ("comparisons", "suggested_action"), ("risks", "suggested_action")):
            self.assertEqual(self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE task_id = ? AND {column} IS NOT NULL", (task_id,),
            ).fetchone()[0], 0)

    def test_error_file_reference_failure_preserves_task(self):
        source = json.loads((ROOT / "docs/fixtures/result/check-partial.json").read_text(encoding="utf-8"))
        import_task(self.conn, source)
        before = list(self.conn.iterdump())
        source["errors"][0]["file_ids"] = ["unknown_file"]
        with self.assertRaisesRegex(ValueError, "unknown file_id"):
            import_task(self.conn, source)
        self.assertEqual(list(self.conn.iterdump()), before)

    def test_risk_and_item_associations_round_trip(self):
        case = self.load_case("multiple_errors_multi")
        import_task(self.conn, case)
        linked_risks = self.conn.execute(
            """SELECT r.item_id, r.comparison_id, COUNT(rf.file_id)
               FROM risks r LEFT JOIN risk_files rf ON rf.risk_id = r.risk_id
               WHERE r.task_id = ? GROUP BY r.risk_id""",
            ("generated_multiple_errors_multi",),
        ).fetchall()
        self.assertTrue(linked_risks)
        self.assertTrue(all(item_id and comparison_id and file_count for item_id, comparison_id, file_count in linked_risks))

        source = {
            "task_id": "field_ownership",
            "status": "COMPLETED",
            "created_at": "2026-10-11T00:00:00+00:00",
            "finished_at": None,
            "input": {"destination_country": "DE"},
            "items": [{"item_id": "item_001", "display_name": "Cup"}],
            "documents": [
                {"file_id": "f1", "file_name": "invoice.json", "file_type": "OTHER",
                 "doc_type": "COMMERCIAL_INVOICE", "process_status": "EXTRACTED"},
                {"file_id": "f2", "file_name": "packing.json", "file_type": "OTHER",
                 "doc_type": "PACKING_LIST", "process_status": "EXTRACTED"},
            ],
            "extractions": [{"file_id": "f1", "fields": [
                {"field_key": key, "item_id": "item_001", "line_no": line,
                 "raw_value": str(line), "normalized_value": line, "status": "EXTRACTED"}
                for key, line in (("item_code", 7), ("unit_price", 8), ("amount", 9))
            ]}],
            "comparisons": [{
                "comparison_id": f"cmp_{key}", "item_id": "item_001", "field_key": key,
                "label": key, "value_type": "STRING", "unit": None, "status": "MATCH",
                "canonical_value": None, "severity": "INFO", "rule_id": None, "note": None,
                "values": [{"file_id": "f1", "file_name": "invoice.json", "item_id": "item_001",
                             "line_no": line, "raw_value": str(line), "normalized_value": line,
                             "field_status": "EXTRACTED"}],
            } for key, line in (("item_code", 7), ("unit_price", 8), ("amount", 9))],
            "risks": [],
        }
        import_task(self.conn, source)
        self.assertEqual(self.conn.execute(
            "SELECT field_key, item_id, line_no FROM extracted_fields WHERE task_id = ? ORDER BY field_key",
            ("field_ownership",),
        ).fetchall(), [("amount", "item_001", 9), ("item_code", "item_001", 7), ("unit_price", "item_001", 8)])
        self.assertEqual(self.conn.execute(
            "SELECT field_key, item_id FROM comparisons WHERE task_id = ? ORDER BY field_key",
            ("field_ownership",),
        ).fetchall(), [("amount", "item_001"), ("item_code", "item_001"), ("unit_price", "item_001")])
        self.assertEqual(self.conn.execute(
            "SELECT item_id, line_no FROM comparison_values WHERE task_id = ? ORDER BY line_no",
            ("field_ownership",),
        ).fetchall(), [("item_001", 7), ("item_001", 8), ("item_001", 9)])


class InitializationTests(unittest.TestCase):
    def test_initialization_is_repeatable_without_losing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.db"
            with patch.object(init_db, "DB_PATH", path), patch("builtins.print"):
                init_db.main()
                conn = sqlite3.connect(path)
                try:
                    import_task(conn, build_cases()[0])
                    before = list(conn.iterdump())
                    init_db.main()
                    self.assertEqual(list(conn.iterdump()), before)
                    self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
                finally:
                    conn.close()

    def test_incompatible_database_is_rejected_without_changes(self):
        for version in (0, 99):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "app.db"
                conn = sqlite3.connect(path)
                try:
                    # 模拟旧开发库或其他版本，拒绝初始化时保留已有记录。
                    conn.executescript("CREATE TABLE tasks (task_id TEXT PRIMARY KEY);"
                                       "INSERT INTO tasks VALUES ('keep_me');")
                    conn.execute(f"PRAGMA user_version = {version}")
                    before = list(conn.iterdump())
                    with patch.object(init_db, "DB_PATH", path), patch("builtins.print"):
                        with self.assertRaisesRegex(SystemExit, "备份"):
                            init_db.main()
                    self.assertEqual(list(conn.iterdump()), before)
                    self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], version)
                finally:
                    conn.close()


if __name__ == "__main__":
    unittest.main()
