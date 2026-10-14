"""HTTP regressions for address revisions and their retained source evidence.

Use synthetic project JSON through the real pipeline, an isolated SQLite store,
and the public correction/report APIs. No source document or OCR fixture is used.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app import main
from app.pipeline import runner
from app.pipeline.trade_json import FORMAT
from app.sqlite_store import TaskStore


ADDRESS_KEYS = ("shipper_address", "consignee_address")


@pytest.fixture
def address_api(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db", tmp_path / "legacy")
    for module in (main, runner):
        monkeypatch.setattr(module, "store", store)
        monkeypatch.setattr(module, "UPLOAD_DIR", tmp_path / "uploads")
    with TestClient(main.app) as client:
        yield client, store


def upload(api, address):
    client, _ = api
    files = []
    for number in range(1, 4):
        document = {
            "format": FORMAT,
            "doc_type": "COMMERCIAL_INVOICE",
            "fields": {
                "document_no": f"CI-SYNTH-{number}",
                "invoice_no": "INV-SYNTH-1",
                "shipper": "Example Export Co., Ltd.",
                "consignee": "Example Import Inc.",
                "shipper_address": address,
                "consignee_address": address,
                "quantity": "500 PCS",
                "packages": "20 CARTONS",
                "gross_weight": "170 KGS",
                "net_weight": "150 KGS",
                "currency": "USD",
                "total_amount": "1400.00",
                "description": "COTTON SHIRT WHITE",
            },
            "line_items": [],
        }
        raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
        files.append(("files", (f"synthetic-{number}.json", raw, "application/json")))
    response = client.post("/api/v1/checks", data={"destination_country": "US"}, files=files)
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/checks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] not in {"PENDING", "PROCESSING"}:
            assert task["status"] == "COMPLETED", task
            assert len(task["documents"]) == 3
            return task
        time.sleep(0.02)
    pytest.fail("synthetic address task did not finish")


def comparison(task, key):
    candidates = [c for c in task["comparisons"] if c["field_key"] == key]
    assert len(candidates) == 1
    return candidates[0]


def address_field(task, key, file_id="f1"):
    extraction = next(e for e in task["extractions"] if e["file_id"] == file_id)
    candidates = [f for f in extraction["fields"] if f["field_key"] == key]
    assert len(candidates) == 1
    return candidates[0]


def correction_payload(client, source, key, value, *, all_files=False):
    context = client.get(f"/api/v1/checks/{source['task_id']}/corrections")
    assert context.status_code == 200, context.text
    file_ids = [d["file_id"] for d in source["documents"]] if all_files else ["f1"]
    return {
        "request_id": "address-regression",
        "source_hash": context.json()["result_hash"],
        "reason": "Synthetic address revision acceptance",
        "changes": [{"file_id": file_id, "field_key": key, "value": value} for file_id in file_ids],
    }


def record_counts(store):
    with sqlite3.connect(store.db_path) as connection:
        return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("api_task_payloads", "correction_audits"))


@pytest.mark.parametrize("key", ADDRESS_KEYS)
@pytest.mark.parametrize("original", [
    "123 Main Rd,Hamburg 20095",
    "１２３ Main Rd, Hamburg 20095",
    "123 Main Rd.",
])
def test_reenter_original_address_preserves_match_and_evidence(address_api, key, original):
    client, store = address_api
    source = upload(address_api, original)
    assert comparison(source, key)["status"] == "MATCH"
    before = address_field(source, key)
    payload = correction_payload(client, source, key, original)
    response = client.post(f"/api/v1/checks/{source['task_id']}/corrections", json=payload)
    assert response.status_code == 200, response.text
    revised = response.json()
    assert revised["task_id"] != source["task_id"]
    assert comparison(revised, key)["status"] == "MATCH"
    after = address_field(revised, key)
    assert after["normalized_value"] == before["normalized_value"]
    assert after["status"] == "LOW_CONFIDENCE"
    assert {k: after[k] for k in ("raw_value", "raw_text", "page", "bbox", "confidence")} == {
        k: before[k] for k in ("raw_value", "raw_text", "page", "bbox", "confidence")
    }
    assert client.get(f"/api/v1/checks/{source['task_id']}").json() == source
    assert record_counts(store) == (2, 1)


@pytest.mark.parametrize("key", ADDRESS_KEYS)
@pytest.mark.parametrize("invalid", ["N/A", "UNKNOWN", "123 Main Rd\x00, Hamburg 20095"])
def test_invalid_address_batch_is_rejected_without_child_or_source_mutation(address_api, key, invalid):
    client, store = address_api
    source = upload(address_api, "123 Main Rd, Hamburg 20095")
    payload = correction_payload(client, source, key, invalid, all_files=True)
    counts = record_counts(store)
    response = client.post(f"/api/v1/checks/{source['task_id']}/corrections", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_CORRECTION"
    assert record_counts(store) == counts == (1, 0)
    assert store.correction_history(source["task_id"]) == []
    assert client.get(f"/api/v1/checks/{source['task_id']}").json() == source


@pytest.mark.parametrize("key", ADDRESS_KEYS)
def test_changed_street_detects_conflict_keeps_original_and_retries_idempotently(address_api, key):
    client, store = address_api
    original = "123 Main Rd, Hamburg 20095"
    source = upload(address_api, original)
    before = address_field(source, key)
    payload = correction_payload(client, source, key, "124 Main Rd, Hamburg 20095")
    endpoint = f"/api/v1/checks/{source['task_id']}/corrections"
    first = client.post(endpoint, json=payload)
    assert first.status_code == 200, first.text
    revised = first.json()
    result = comparison(revised, key)
    assert result["status"] == "CONFLICT"
    assert result["canonical_value"] is None
    assert len(result["values"]) == 3
    after = address_field(revised, key)
    assert after["normalized_value"] == "124 MAIN RD, HAMBURG 20095"
    assert after["raw_value"] == before["raw_value"] == original
    assert after["raw_text"] == before["raw_text"]
    second = client.post(endpoint, json=payload)
    assert second.status_code == 200, second.text
    assert second.json() == revised
    assert record_counts(store) == (2, 1)
    assert client.get(f"/api/v1/checks/{source['task_id']}").json() == source
    report = client.get(f"/api/v1/checks/{revised['task_id']}/report")
    assert report.status_code == 200, report.text
    assert comparison(report.json(), key)["status"] == "CONFLICT"
    archive = client.get(f"/api/v1/checks/{revised['task_id']}/report?view=archive")
    assert archive.status_code == 200, archive.text
    archived = archive.json()
    assert archived["task"]["task_id"] == revised["task_id"]
    assert archived["task"]["summary"]["conflict_count"] == revised["summary"]["conflict_count"]
    assert archived["corrections"][0]["changes"][0]["before"]["raw_value"] == original
    assert archived["corrections"][0]["changes"][0]["after"]["raw_value"] == original
