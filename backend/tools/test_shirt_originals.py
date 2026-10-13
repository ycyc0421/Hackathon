"""Manual HTTP regression for the three original shirt PDFs from issue #38."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ["PADDLE_OCR_ENABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app import main
from app.pipeline import runner
from app.sqlite_store import TaskStore

ROOT = Path(__file__).resolve().parents[1] / "samples" / "shirt-originals"
FILES_PATTERN = '*.pdf'


def verify(result: dict) -> None:
    task = result["task"]
    assert result["report_status"] == 200
    assert task["status"] == "COMPLETED", task["errors"]
    documents = {d["file_id"]: d for d in task["documents"]}
    assert len(documents) == 3
    descriptions = [c for c in task['comparisons'] if c['field_key'] == 'description' and c.get('scope') == 'ITEM']
    assert descriptions and all(c['status'] == 'NOT_CHECKED' and c['note'] for c in descriptions), descriptions
    for extraction in task["extractions"]:
        document = documents[extraction["file_id"]]
        assert document["process_status"] == "EXTRACTED", document
        fields = {f["field_key"]: f for f in extraction["fields"]}
        packing = document["doc_type"] == "PACKING_LIST"
        prefix = "PL" if packing else ("PI" if "proforma" in document["file_name"] else "CI")
        expected = {"document_no": f"{prefix}-20260830-08300186",
                    "shipper": "NINGBO QIHANG EXPORT CO., LTD",
                    "consignee": "GLOBAL FASHION INC"}
        if not packing:
            expected["total_amount"] = 1400
        for key, value in expected.items():
            assert fields[key]["normalized_value"] == value, (document, key, fields[key])
            assert fields[key]["page"] == 1 and fields[key]["raw_text"]
        assert len(extraction["line_items"]) == 1
        row = {f["field_key"]: f for f in extraction["line_items"][0]["fields"]}
        values = {"item_code": "CT-2408", "quantity": 500}
        values.update({"packages": 20, "net_weight": 150, "gross_weight": 170, "volume": 1.68}
                      if packing else {"unit_price": 2.8, "amount": 1400})
        for key, value in values.items():
            assert row[key]["normalized_value"] == value, (document, key, row[key])
            assert row[key]["page"] == 1 and row[key]["raw_text"]
        if packing:
            for field in (fields["total_amount"], row["amount"]):
                assert field["normalized_value"] is None and field["status"] == "NOT_IN_DOC", field


def run() -> dict:
    temp_parent = Path(__file__).resolve().parents[1] / ".out" / "shirt"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temp_parent) as directory:
        root = Path(directory)
        store = TaskStore(root / "tasks.db", root / "legacy")
        with patch.object(main, "store", store), patch.object(runner, "store", store), patch.object(runner, "UPLOAD_DIR", root / "uploads"):
            with TestClient(main.app) as client:
                response = client.post(
                    "/api/v1/checks",
                    data={"destination_country": "US"},
                    files=[("files", (path.name, path.read_bytes(),
                                      "application/pdf" if path.suffix.lower() == '.pdf' else 'image/png'))
                           for path in sorted(ROOT.glob(FILES_PATTERN))],
                )
                response.raise_for_status()
                task_id = response.json()["task_id"]
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    task = store.get(task_id)
                    if task and task["status"] in {"COMPLETED", "PARTIAL", "FAILED"}:
                        report = client.get(f"/api/v1/checks/{task_id}/report?format=json")
                        report.raise_for_status()
                        public = client.get(f"/api/v1/checks/{task_id}")
                        public.raise_for_status()
                        return {"task": task, "public_task": public.json(), "report_status": report.status_code, "report": report.json()}
                    time.sleep(0.5)
                raise TimeoutError(f"Task {task_id} did not finish in 300 seconds")


if __name__ == "__main__":
    result = run()
    out = Path(__file__).resolve().parents[1] / ".out" / "shirt" / "http-result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    verify(result)
    task = result["task"]
    print(json.dumps({"task_id": task["task_id"], "status": task["status"],
                      "documents": task["documents"], "summary": task["summary"],
                      "errors": task["errors"], "report_status": result["report_status"]}, ensure_ascii=False))
