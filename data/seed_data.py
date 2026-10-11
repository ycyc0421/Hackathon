"""Load the repository's completed fixture into the local SQLite database."""
from pathlib import Path
import json
import sqlite3
import argparse

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "app.db"
FIXTURE_PATH = ROOT / "docs" / "fixtures" / "result" / "check-completed.json"
ITEM_FIELDS = {
    "description", "hs_code", "packages", "quantity", "gross_weight",
    "net_weight", "volume", "total_amount", "currency",
}


def dump_json(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


def item_catalog(data):
    """Read an explicit items[] catalog, or infer the current single-item fixture."""
    if data.get("items"):
        return data["items"]
    return [{
        "item_id": "item_001",
        "display_name": "陶瓷马克杯",
        "description": "CERAMIC MUG 350ML WHITE",
        "line_no": 1,
    }]


def main() -> None:
    parser = argparse.ArgumentParser(description="将任务样例导入 SQLite")
    parser.add_argument("--input", type=Path, default=FIXTURE_PATH)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    # Generated internal cases wrap task data and use the same documents/items concepts.
    if "task" in data and "task_id" not in data:
        task = data.pop("task")
        data = {
            "task_id": task["task_id"],
            "status": "COMPLETED",
            "created_at": task["created_at"],
            "finished_at": None,
            "input": {"destination_country": task["destination_country"]},
            "items": data.get("items", []),
            "documents": data.get("documents", []),
            "extractions": [],
            "comparisons": [],
            "risks": data.get("expected", {}).get("risks", []),
        }
        # Adapt the generator's internal document shape to the storage shape.
        for doc in data["documents"]:
            doc.setdefault("file_type", "OTHER")
            doc.setdefault("page_count", None)
            doc.setdefault("process_status", "EXTRACTED")
            doc.setdefault("error_message", None)
        data["extractions"] = [
            {"file_id": doc["file_id"], "doc_type": doc["doc_type"],
             "parse_method": doc.get("parse_method"), "fields": doc["fields"]}
            for doc in data["documents"]
        ]
        data["comparisons"] = []
        file_names = {doc["file_id"]: doc["file_name"] for doc in data["documents"]}
        for comparison in data.get("expected", {}).get("comparisons", []):
            field_key = comparison["field_key"]
            value_type = "NUMBER" if field_key in {"quantity", "packages", "gross_weight", "net_weight", "volume"} else "STRING"
            values = [dict(v, file_name=file_names[v["file_id"]]) for v in comparison["values"]]
            data["comparisons"].append({
                **comparison, "label": field_key, "value_type": value_type,
                "unit": values[0].get("unit"), "severity": "ERROR" if comparison["status"] == "CONFLICT" else "INFO",
                "rule_id": None, "note": comparison.get("note"),
                "canonical_value": None, "values": values,
            })
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM tasks WHERE task_id = ?", (data["task_id"],))
        conn.execute(
            """INSERT INTO tasks (task_id,status,destination_country,destination_country_name,
            trade_mode,declared_currency,notes,created_at,finished_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (data["task_id"], data["status"], data["input"]["destination_country"],
             data["input"].get("destination_country_name"), data["input"].get("trade_mode"),
             data["input"].get("declared_currency"), data["input"].get("notes"),
             data["created_at"], data["finished_at"]),
        )
        for item_row in item_catalog(data):
            conn.execute(
                """INSERT INTO items (task_id,item_id,display_name,description,line_no)
                VALUES (?,?,?,?,?)""",
                (data["task_id"], item_row["item_id"], item_row.get("display_name", item_row.get("description", "")),
                 item_row.get("description"), item_row.get("line_no", item_row.get("item_order"))),
            )
        for doc in data["documents"]:
            conn.execute(
                """INSERT INTO documents
                (file_id,task_id,file_name,file_type,doc_type,process_status,page_count,error_message)
                VALUES (?,?,?,?,?,?,?,?)""",
                (doc["file_id"], data["task_id"], doc["file_name"], doc["file_type"],
                 doc["doc_type"], doc["process_status"], doc["page_count"], doc["error_message"]),
            )
        for extraction in data["extractions"]:
            for field in extraction["fields"]:
                conn.execute(
                    """INSERT INTO extracted_fields
                    (task_id,file_id,item_id,line_no,field_key,label,raw_text,raw_value,
                     normalized_value_json,unit,confidence,status,page,bbox_json,bbox_unit)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (data["task_id"], extraction["file_id"],
                     field.get("item_id") if field["field_key"] in ITEM_FIELDS else None,
                     field.get("line_no") if field["field_key"] in ITEM_FIELDS else None,
                     field["field_key"], field.get("label", field["field_key"]), field.get("raw_text", field.get("raw_value")),
                     field.get("raw_value"), dump_json(field.get("normalized_value")), field.get("unit"),
                     field.get("confidence"), field["status"], field.get("page"),
                     dump_json(field.get("bbox")), field.get("bbox_unit")),
                )
        for comparison in data["comparisons"]:
            conn.execute(
                """INSERT INTO comparisons
                (comparison_id,task_id,item_id,field_key,label,value_type,unit,status,canonical_value_json,
                 severity,rule_id,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (comparison["comparison_id"], data["task_id"],
                 comparison.get("item_id") if comparison["field_key"] in ITEM_FIELDS else None,
                 comparison["field_key"],
                 comparison["label"], comparison["value_type"], comparison["unit"],
                 comparison["status"], dump_json(comparison["canonical_value"]),
                 comparison["severity"], comparison.get("rule_id"), comparison.get("note")),
            )
            for value in comparison["values"]:
                conn.execute(
                    """INSERT INTO comparison_values
                    (comparison_id,task_id,item_id,file_id,line_no,file_name,raw_value,
                     normalized_value_json,field_status,page,bbox_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (comparison["comparison_id"], data["task_id"],
                     comparison.get("item_id") if comparison["field_key"] in ITEM_FIELDS else None,
                     value["file_id"], value.get("line_no"), value["file_name"],
                     value["raw_value"], dump_json(value["normalized_value"]), value["field_status"],
                     value.get("page"), dump_json(value.get("bbox"))),
                )
        for risk in data["risks"]:
            conn.execute(
                """INSERT INTO risks
                (risk_id,task_id,risk_type,severity,title,detail,destination_country,rule_id,rule_source)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (risk["risk_id"], data["task_id"], risk.get("type", "OTHER"), risk.get("severity", "WARNING"),
                 risk.get("title", "Synthetic review"), risk.get("detail", risk.get("title", "Synthetic review")),
                 risk.get("destination_country", data["input"]["destination_country"]), risk.get("rule_id"), risk.get("rule_source")),
            )
            for field_key in risk["related_field_keys"]:
                conn.execute("INSERT INTO risk_fields (risk_id,field_key) VALUES (?,?)", (risk["risk_id"], field_key))
    print(f"已导入任务 {data['task_id']}：{DB_PATH}")


if __name__ == "__main__":
    main()
