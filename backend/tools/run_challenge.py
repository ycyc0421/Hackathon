"""把「格式与语言不统一」挑战样例打进真实接口，输出判定结果。

    python tools/run_challenge.py

对 samples/09~11 三套样例各跑一次（PDF，文本层通道），另对 09 的
PNG 图片单独跑一次（图片通道探针：未配置多模态时应显式失败）。
返回体存到 .out/challenge/，控制台打印与金标预期（samples/challenge/金标预期.md）
逐项对照所需的全部信息。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLES_DIR = BACKEND_DIR / "samples"
OUT_DIR = BACKEND_DIR / ".out" / "challenge"

PDF_CASES = [
    ("09_us_format_mixed", "US", "美国"),
    ("10_de_ambiguity_conflict", "DE", "德国"),
    ("11_de_multiitem_mixed", "DE", "德国"),
]
# 图片通道探针：当前未配置多模态，预期所有文件显式 FAILED
PNG_PROBE = ("09_us_format_mixed", "US", "美国")

TERMINAL = {"COMPLETED", "PARTIAL", "FAILED"}
WATCH_FIELD_STATUS = {"NORMALIZE_FAILED", "UNRECOGNIZED", "MISSING_IN_DOC", "LOW_CONFIDENCE"}


def upload(client: TestClient, dir_name: str, cc: str, cname: str, suffixes: list[str], wait_seconds: int = 90) -> dict:
    d = SAMPLES_DIR / dir_name
    files = []
    for p in sorted(d.iterdir()):
        if p.suffix.lower() in suffixes:
            mime = "application/pdf" if p.suffix.lower() == ".pdf" else "image/png"
            files.append(("files", (p.name, p.read_bytes(), mime)))
    resp = client.post(
        "/api/v1/checks",
        data={"destination_country": cc, "destination_country_name": cname},
        files=files,
    )
    if resp.status_code != 200:
        raise SystemExit(f"POST 失败 {resp.status_code}: {resp.text[:300]}")
    task_id = resp.json()["task_id"]

    for _ in range(int(wait_seconds / 0.3)):
        task = client.get(f"/api/v1/checks/{task_id}").json()
        if task["status"] in TERMINAL:
            return task
        time.sleep(0.3)
    raise SystemExit(f"{dir_name}: {wait_seconds} 秒内未出结果")


def report(task: dict, title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
    print(f"status = {task['status']}   summary = {task['summary']}")
    if task.get("errors"):
        for e in task["errors"]:
            print(f"  error[{e['level']}] {e['code']}: {e['message'][:80]}")

    for d in task["documents"]:
        err = f"  ({d['error_message'][:60]})" if d.get("error_message") else ""
        print(f"  文件 {d['file_name']}: {d['doc_type']} / {d['process_status']}{err}")

    notable = []
    for ext in task["extractions"]:
        for f in ext["fields"]:
            if f["status"] in WATCH_FIELD_STATUS:
                notable.append(
                    f"  [{ext['file_id']}] {f['field_key']:<18} {f['status']:<16}"
                    f" raw={str(f['raw_value'])[:40]!r}"
                )
    if notable:
        print("  --- 抽取层值得注意的状态 ---")
        print("\n".join(notable))

    if task.get("items"):
        print(f"  行组: {len(task['items'])} 组")

    match_n = 0
    for c in task["comparisons"]:
        if c["status"] == "MATCH":
            match_n += 1
            continue
        scope = f"/{c.get('item_id')}" if c.get("item_id") else ""
        vals = "  vs  ".join(
            f"{v['file_id']}:{v['normalized_value']!r}({v['field_status']})" for v in c["values"]
        )
        print(f"  [{c['status']}:{c['severity']}]{scope} {c['field_key']}")
        print(f"      {vals}")
        if c.get("note"):
            print(f"      note: {c['note'][:90]}")
    print(f"  MATCH 共 {match_n} 项")

    for r in task["risks"]:
        item = f" 行组{r['related_item_ids']}" if r.get("related_item_ids") else ""
        print(f"  risk[{r['severity']}] {r['type']}{item} {r['title'][:70]}")


def verify_gold(tasks: dict[str, dict]) -> None:
    """只断言挑战样例的关键结论，避免误把打印输出当作验收。"""
    def field(task: dict, file_part: str, key: str) -> dict:
        files = {d["file_id"]: d["file_name"] for d in task["documents"]}
        return next(
            f for ext in task["extractions"] if file_part in files[ext["file_id"]]
            for f in ext["fields"] if f["field_key"] == key and f["item_id"] is None
        )

    def comparison(task: dict, key: str, status: str, item_level: bool = False) -> bool:
        return any(
            c["field_key"] == key and c["status"] == status
            and (c["item_id"] is not None) == item_level
            for c in task["comparisons"]
        )

    us = tasks["09_us_format_mixed"]
    de = tasks["10_de_ambiguity_conflict"]
    multi = tasks["11_de_multiitem_mixed"]
    assert us["summary"]["conflict_count"] == 0
    assert all(field(us, name, "shipment_date")["normalized_value"] == "2026-10-08"
               for name in ("Bill-of-Lading", "Packing-List", "商业发票"))
    assert field(de, "Packing-List", "gross_weight")["normalized_value"] == 2400
    assert field(de, "Packing-List", "shipment_date")["status"] == "NORMALIZE_FAILED"
    assert field(de, "商业发票", "shipment_date")["normalized_value"] == "2026-10-05"
    assert field(de, "商业发票", "currency")["normalized_value"] == "USD"
    assert comparison(de, "gross_weight", "MATCH")
    assert comparison(de, "quantity", "CONFLICT")
    assert comparison(de, "total_amount", "CONFLICT")
    assert comparison(de, "currency", "CONFLICT")
    assert len(multi["items"]) == 4
    assert field(multi, "商业发票", "quantity")["normalized_value"] == 9600
    assert field(multi, "商业发票", "total_amount")["normalized_value"] == 13500
    assert field(multi, "商业发票", "description")["status"] == "NOT_IN_DOC"
    assert comparison(multi, "description", "CONFLICT", item_level=True)
    assert tasks["png_probe"]["status"] == "FAILED"
    assert any(e["code"] == "DOC_PARSE_FAILED" for e in tasks["png_probe"]["errors"])
    print("\n挑战样例关键金标断言：全部通过")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    tasks: dict[str, dict] = {}

    for dir_name, cc, cname in PDF_CASES:
        task = upload(client, dir_name, cc, cname, [".pdf"])
        tasks[dir_name] = task
        (OUT_DIR / f"{dir_name}.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        report(task, f"{dir_name}  （PDF 文本层通道，目的国 {cname}）")

    dir_name, cc, cname = PNG_PROBE
    task = upload(client, dir_name, cc, cname, [".png"])
    tasks["png_probe"] = task
    (OUT_DIR / f"{dir_name}__png_probe.json").write_text(
        json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report(task, f"{dir_name}  （PNG 图片通道探针 —— 未配置多模态，预期显式失败）")

    verify_gold(tasks)

    print(f"\n返回体已写入 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
