"""合成单证的接口、业务结论与 JSON Schema 回归，不代表真实 OCR 准确率。"""
import json
from pathlib import Path
import shutil
import subprocess
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "backend/samples"
MIME = {".pdf": "application/pdf", ".png": "image/png"}
pytestmark = pytest.mark.integration

# 预期来自 make_samples.py 中的造数意图，不从本次后端返回推导。
# 每项依次为文件数、商品数、冲突的（字段、是否商品级）集合。
SAMPLE_EXPECTATIONS = {
    "01_us_consistent": (3, 0, set()),
    "02_de_conflict": (3, 0, {("packages", False), ("gross_weight", False)}),
    "03_de_partial": (3, 0, set()),
    "04_de_multiitem": (3, 4, set()),
    "05_de_multiitem_conflict": (2, 4, {
        ("packages", False), ("total_amount", False), ("description", True),
        ("packages", True), ("amount", True), ("hs_code", True),
    }),
    "06_de_multiitem_gap": (3, 5, {("packages", False), ("gross_weight", False)}),
    "07_de_multiitem_unaligned": (2, 2, set()),
    "08_de_bilingual_format": (2, 4, set()),
}


@pytest.fixture
def validate_response(tmp_path):
    node = shutil.which("node")
    assert node is not None, "接口契约测试需要 Node.js；请安装后执行 npm ci"

    def validate(payload, name="task", report=False):
        output = tmp_path / name
        output.mkdir()
        (output / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        script = "validate_reports.mjs" if report else "validate_outputs.mjs"
        result = subprocess.run(
            [node, str(REPO_ROOT / "backend/tools" / script), str(output)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    return validate


def upload(client, name, suffixes=(".pdf", ".png")):
    directory = SAMPLES / name
    assert directory.is_dir(), f"缺少必需样例：{directory}"
    files = sorted(path for path in directory.iterdir() if path.suffix in suffixes)
    assert files, f"样例没有 {suffixes} 文件：{directory}"
    response = client.post(
        "/api/v1/checks", data={"destination_country": "US" if "_us_" in name else "DE"},
        files=[("files", (path.name, path.read_bytes(), MIME[path.suffix])) for path in files],
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/checks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] in {"COMPLETED", "PARTIAL", "FAILED"}:
            assert len(task["documents"]) == len(files)
            return task
        time.sleep(0.02)
    pytest.fail(f"{name} 未在 15 秒内完成，最后状态：{task['status']}")


def field(task, file_part, key):
    files = {document["file_id"]: document["file_name"] for document in task["documents"]}
    return next(
        field for extraction in task["extractions"] if file_part in files[extraction["file_id"]]
        for field in extraction["fields"] if field["field_key"] == key and field["item_id"] is None
    )


def comparison(task, key, status, item_level=False):
    return any(
        value["field_key"] == key and value["status"] == status
        and (value["item_id"] is not None) == item_level
        for value in task["comparisons"]
    )


@pytest.mark.parametrize("name", SAMPLE_EXPECTATIONS)
def test_sample_contract_and_actions(client, validate_response, name):
    task = upload(client, name)
    validate_response(task, name)
    assert task["status"] == ("PARTIAL" if name == "03_de_partial" else "COMPLETED")
    document_count, item_count, conflicts = SAMPLE_EXPECTATIONS[name]
    assert len(task["documents"]) == document_count
    assert len(task["items"]) == item_count
    assert {
        (value["field_key"], value["item_id"] is not None)
        for value in task["comparisons"] if value["status"] == "CONFLICT"
    } == conflicts
    for value in task["comparisons"]:
        if value["status"] in {"CONFLICT", "MISSING_IN_SOME", "NOT_CHECKED"}:
            assert value.get("suggested_action"), value
        elif value["status"] in {"MATCH", "SINGLE_SOURCE"}:
            assert value.get("suggested_action") is None, value
    for error in task["errors"]:
        if error["code"] == "DOC_PARSE_FAILED":
            assert "建议：" in error["message"]
    if name == "03_de_partial":
        assert sum(d["process_status"] == "FAILED" for d in task["documents"]) == 1
        assert any(error["code"] == "DOC_PARSE_FAILED" for error in task["errors"])
    if name == "07_de_multiitem_unaligned":
        item_comparisons = [value for value in task["comparisons"] if value["item_id"]]
        assert item_comparisons
        assert all(value["status"] == "NOT_CHECKED" for value in item_comparisons)
    if name == "08_de_bilingual_format":
        descriptions = [c for c in task["comparisons"] if c["field_key"] == "description" and c["item_id"]]
        dates = [c for c in task["comparisons"] if c["field_key"] == "shipment_date"]
        assert len(task["items"]) == len(descriptions) == 4
        assert all(c["status"] == "MATCH" for c in descriptions)
        assert len(dates) == 1 and dates[0]["status"] == "MATCH"
        assert {v["raw_value"] for v in dates[0]["values"]} == {"2026-10-10", "2026/10/10"}
        assert task["summary"]["conflict_count"] == task["summary"]["missing_count"] == 0


def test_mixed_formats_agree(client, validate_response):
    task = upload(client, "09_us_format_mixed", (".pdf",))
    validate_response(task)
    assert task["status"] == "COMPLETED"
    assert task["summary"]["conflict_count"] == 0
    for name in ("Bill-of-Lading", "Packing-List", "商业发票"):
        assert field(task, name, "shipment_date")["normalized_value"] == "2026-10-08"
    assert comparison(task, "shipment_date", "MATCH")


def test_ambiguity_and_real_conflicts(client, validate_response):
    task = upload(client, "10_de_ambiguity_conflict", (".pdf",))
    validate_response(task)
    assert task["status"] == "COMPLETED"
    assert field(task, "Packing-List", "gross_weight")["normalized_value"] == 2400
    assert field(task, "Packing-List", "shipment_date")["status"] == "NORMALIZE_FAILED"
    assert field(task, "商业发票", "shipment_date")["normalized_value"] == "2026-10-05"
    assert field(task, "商业发票", "currency")["normalized_value"] == "USD"
    assert comparison(task, "gross_weight", "MATCH")
    for key in ("quantity", "total_amount", "currency"):
        assert comparison(task, key, "CONFLICT"), key


def test_multiitem_color_conflict(client, validate_response):
    task = upload(client, "11_de_multiitem_mixed", (".pdf",))
    validate_response(task)
    assert task["status"] == "COMPLETED"
    assert len(task["items"]) == 4
    assert field(task, "商业发票", "quantity")["normalized_value"] == 9600
    assert field(task, "商业发票", "total_amount")["normalized_value"] == 13500
    assert field(task, "商业发票", "description")["status"] == "NOT_IN_DOC"
    assert comparison(task, "description", "CONFLICT", item_level=True)


def test_images_without_ocr_fail_explicitly(client, validate_response):
    task = upload(client, "09_us_format_mixed", (".png",))
    validate_response(task)
    assert task["status"] == "FAILED"
    assert all(document["process_status"] == "FAILED" for document in task["documents"])
    assert any(error["code"] == "DOC_PARSE_FAILED" for error in task["errors"])
    assert not any(value["status"] == "MATCH" for value in task["comparisons"])


def test_evaluation_is_not_run(client, validate_response):
    response = client.get("/api/v1/evaluation/latest")
    assert response.status_code == 200, response.text
    validate_response(response.json(), "evaluation")
    assert response.json()["status"] == "NOT_RUN"


def test_correction_export_and_reopen(tmp_path, validate_response):
    # 此工具同时保留给手工候选验收；内部逐项断言完整的修正和导出链路。
    from tools.accept_workflow import run

    output = tmp_path / "workflow"
    run(output)
    result = json.loads((output / "acceptance.json").read_text(encoding="utf-8"))
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    validate_response(report, "report", report=True)
    assert result["status"] == "PASSED"
    assert "reopened_database_readable" in result["checks"]
