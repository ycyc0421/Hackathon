"""Import formal task fixtures or internal synthetic cases atomically into SQLite."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "app.db"
FIXTURE_PATH = ROOT / "docs" / "fixtures" / "result" / "check-completed.json"


def scoped_id(task_id, local_id):
    """Make task-local fixture IDs unique inside the shared SQLite database."""
    return json.dumps([task_id, local_id], ensure_ascii=False, separators=(",", ":"))


def dump_json(value):
    return None if value is None else json.dumps(value, ensure_ascii=False, allow_nan=False)


def adapt_task(source):
    """Adapt the generator's internal shape without losing expected results."""
    data = deepcopy(source)
    data.pop("_comment", None)
    if "task" not in data or "task_id" in data:
        data.setdefault("items", [])
        return data

    task = data["task"]
    expected = data.get("expected", {})
    documents = data.get("documents", [])
    for doc in documents:
        doc.setdefault("file_type", "OTHER")
        doc.setdefault("page_count", None)
        doc.setdefault("process_status", "EXTRACTED")
        doc.setdefault("error_message", None)
    file_names = {doc["file_id"]: doc["file_name"] for doc in documents}
    value_types = {
        "quantity": "NUMBER", "packages": "NUMBER", "gross_weight": "NUMBER",
        "net_weight": "NUMBER", "volume": "NUMBER", "hs_code": "CODE",
        "currency": "CODE", "total_amount": "MONEY", "shipment_date": "DATE",
    }
    comparisons = []
    for comparison in expected.get("comparisons", []):
        values = [dict(value, file_name=file_names[value["file_id"]])
                  for value in comparison["values"]]
        comparisons.append({
            **comparison,
            "label": comparison["field_key"],
            "value_type": value_types.get(comparison["field_key"], "STRING"),
            "unit": values[0].get("unit") if values else None,
            "severity": "ERROR" if comparison["status"] == "CONFLICT" else "INFO",
            "rule_id": None,
            "canonical_value": None,
            "values": values,
        })
    return {
        "task_id": task["task_id"],
        "status": "COMPLETED",
        "created_at": task["created_at"],
        "finished_at": None,
        "input": {"destination_country": task["destination_country"]},
        "items": data.get("items", []),
        "documents": documents,
        "extractions": [
            {"file_id": doc["file_id"], "doc_type": doc["doc_type"],
             "parse_method": doc.get("parse_method"), "fields": doc["fields"]}
            for doc in documents
        ],
        "comparisons": comparisons,
        "risks": expected.get("risks", []),
    }


def validate_references(data):
    """Validate task-local references before writing any rows."""
    def unique(rows, key):
        values = [row[key] for row in rows]
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {key}")
        return set(values)

    item_ids = unique(data["items"], "item_id")
    file_ids = unique(data["documents"], "file_id")
    comparison_ids = unique(data["comparisons"], "comparison_id")
    unique(data["risks"], "risk_id")

    def item_ref(row):
        if row.get("item_id") is not None and row["item_id"] not in item_ids:
            raise ValueError(f"unknown item_id: {row['item_id']}")

    def file_ref(value):
        if value not in file_ids:
            raise ValueError(f"unknown file_id: {value}")

    for extraction in data["extractions"]:
        file_ref(extraction["file_id"])
        for field in extraction["fields"]:
            item_ref(field)
    for comparison in data["comparisons"]:
        item_ref(comparison)
        for value in comparison["values"]:
            file_ref(value["file_id"])
            item_ref(value)
            if "item_id" in value and value["item_id"] != comparison.get("item_id"):
                raise ValueError("comparison value item_id differs from its comparison")
    for risk in data["risks"]:
        item_ref(risk)
        if risk.get("comparison_id") is not None and risk["comparison_id"] not in comparison_ids:
            raise ValueError(f"unknown comparison_id: {risk['comparison_id']}")
        for file_id in risk.get("related_file_ids", []):
            file_ref(file_id)
    for error in data.get("errors", []):
        for file_id in error.get("file_ids", []):
            file_ref(file_id)


def import_task(conn, source, *, payload_json=None):
    data = adapt_task(source)
    validate_references(data)
    task_id = data["task_id"]
    storage_id = lambda value: scoped_id(task_id, value)
    parse_methods = {e["file_id"]: e.get("parse_method") for e in data["extractions"]}
    conn.execute("PRAGMA foreign_keys = ON")
    with conn:
        # Deleting one task cascades only its rows; the transaction preserves old data on error.
        conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        info = data["input"]
        conn.execute(
            """INSERT INTO tasks (task_id,status,destination_country,destination_country_name,
            trade_mode,declared_currency,notes,created_at,finished_at,errors_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (task_id, data["status"], info["destination_country"], info.get("destination_country_name"),
             info.get("trade_mode"), info.get("declared_currency"), info.get("notes"),
             data["created_at"], data.get("finished_at"), dump_json(data.get("errors", []))),
        )
        for item in data["items"]:
            conn.execute(
                """INSERT INTO items (task_id,item_id,display_name,description,line_no)
                VALUES (?,?,?,?,?)""",
                (task_id, item["item_id"], item.get("display_name", item.get("label", item["item_id"])), item.get("description"),
                 item.get("line_no", item.get("item_order"))),
            )
        for doc in data["documents"]:
            conn.execute(
                """INSERT INTO documents
                (file_id,task_id,file_name,file_type,doc_type,process_status,page_count,error_message,parse_method)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (storage_id(doc["file_id"]), task_id, doc["file_name"], doc["file_type"],
                 doc.get("doc_type"), doc["process_status"], doc.get("page_count"), doc.get("error_message"),
                 parse_methods.get(doc["file_id"])),
            )
        for extraction in data["extractions"]:
            for field in extraction["fields"]:
                conn.execute(
                    """INSERT INTO extracted_fields
                    (task_id,file_id,item_id,line_no,field_key,label,raw_text,raw_value,
                     normalized_value_json,unit,confidence,status,page,bbox_json,bbox_unit)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id, storage_id(extraction["file_id"]), field.get("item_id"), field.get("line_no"),
                     field["field_key"], field.get("label", field["field_key"]),
                     field.get("raw_text", field.get("raw_value")), field.get("raw_value"),
                     dump_json(field.get("normalized_value")), field.get("unit"), field.get("confidence"),
                     field["status"], field.get("page"), dump_json(field.get("bbox")), field.get("bbox_unit")),
                )
        for comparison in data["comparisons"]:
            comparison_id = storage_id(comparison["comparison_id"])
            conn.execute(
                """INSERT INTO comparisons
                (comparison_id,task_id,item_id,field_key,label,value_type,unit,status,canonical_value_json,
                 severity,rule_id,note,suggested_action) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (comparison_id, task_id, comparison.get("item_id"), comparison["field_key"],
                 comparison["label"], comparison["value_type"], comparison.get("unit"), comparison["status"],
                 dump_json(comparison.get("canonical_value")), comparison["severity"],
                 comparison.get("rule_id"), comparison.get("note"), comparison.get("suggested_action")),
            )
            for value in comparison["values"]:
                conn.execute(
                    """INSERT INTO comparison_values
                    (comparison_id,task_id,item_id,file_id,line_no,file_name,raw_value,
                     normalized_value_json,field_status,page,bbox_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (comparison_id, task_id, value.get("item_id", comparison.get("item_id")),
                     storage_id(value["file_id"]), value.get("line_no"), value["file_name"],
                     value.get("raw_value"), dump_json(value.get("normalized_value")),
                     value["field_status"], value.get("page"), dump_json(value.get("bbox"))),
                )
        for risk in data["risks"]:
            risk_id = storage_id(risk["risk_id"])
            comparison_id = storage_id(risk["comparison_id"]) if risk.get("comparison_id") else None
            conn.execute(
                """INSERT INTO risks
                (risk_id,task_id,item_id,comparison_id,risk_type,severity,title,detail,
                 destination_country,rule_id,rule_source,suggested_action)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (risk_id, task_id, risk.get("item_id"), comparison_id, risk.get("type", "OTHER"),
                 risk.get("severity", "WARNING"), risk.get("title", "Synthetic review"),
                 risk.get("detail", risk.get("title", "Synthetic review")),
                 risk.get("destination_country", info["destination_country"]), risk.get("rule_id"),
                 risk.get("rule_source"), risk.get("suggested_action")),
            )
            for field_key in risk["related_field_keys"]:
                conn.execute("INSERT INTO risk_fields (risk_id,field_key) VALUES (?,?)", (risk_id, field_key))
            for position, file_id in enumerate(risk.get("related_file_ids", [])):
                conn.execute(
                    "INSERT INTO risk_files (risk_id,file_id,position) VALUES (?,?,?)",
                    (risk_id, storage_id(file_id), position),
                )
        expected = (len(data["comparisons"]), sum(len(c["values"]) for c in data["comparisons"]))
        actual = tuple(
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE task_id = ?", (task_id,)).fetchone()[0]
            for table in ("comparisons", "comparison_values")
        )
        if actual != expected:
            raise RuntimeError(f"comparison import count mismatch: expected {expected}, got {actual}")
        if payload_json is not None:
            conn.execute("INSERT INTO api_task_payloads(task_id,payload_json) VALUES (?,?)", (task_id, payload_json))
    return task_id


def main():
    parser = argparse.ArgumentParser(description="将任务样例导入 SQLite")
    parser.add_argument("--input", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    with sqlite3.connect(args.db) as conn:
        task_id = import_task(conn, source)
    print(f"已导入任务 {task_id}：{args.db}")


if __name__ == "__main__":
    main()
