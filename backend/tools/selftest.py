"""端到端自检：打真实接口，产出结果，再按契约校验。

    python tools/selftest.py            # 跑接口 + 当前契约校验
    python tools/selftest.py --no-node  # 只跑接口，输出到 .out/

这一步就是 W1 的验收标准：**后端返回的 JSON 能通过 schema 校验。**

对外返回直接按仓库当前 docs/schema/check-task.schema.json 校验。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent          # Hackathon/
SAMPLES_DIR = BACKEND_DIR / "samples"
OUT_DIR = BACKEND_DIR / ".out"

sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# 每套样例对应的目的国
CASES = [
    ("01_us_consistent", "US", "美国"),
    ("02_de_conflict", "DE", "德国"),
    ("03_de_partial", "DE", "德国"),
    # 多品名（v0.2）
    ("04_de_multiitem", "DE", "德国"),
    ("05_de_multiitem_conflict", "DE", "德国"),
    ("06_de_multiitem_gap", "DE", "德国"),
    ("07_de_multiitem_unaligned", "DE", "德国"),
    ("08_de_bilingual_format", "DE", "德国"),
]

MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

# 使用系统 PATH 上的 Node.js，避免把个人电脑路径写进仓库。
NODE_CANDIDATES = [shutil.which("node")]


def find_node() -> str | None:
    for cand in NODE_CANDIDATES:
        if cand and Path(cand).exists():
            return cand
    return None


def post_case(client: TestClient, name: str, country: str, country_name: str) -> dict:
    folder = SAMPLES_DIR / name
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in MIME)
    payload = [("files", (p.name, p.read_bytes(), MIME[p.suffix.lower()])) for p in files]
    resp = client.post(
        "/api/v1/checks",
        files=payload,
        data={
            "destination_country": country,
            "destination_country_name": country_name,
        },
    )
    if resp.status_code != 200:
        print(f"  ❌ {name}  HTTP {resp.status_code}：{resp.text[:200]}")
        return {}
    return resp.json()


def brief(name: str, task: dict) -> None:
    if not task:
        return
    s = task["summary"]
    print(f"  · {name}")
    print(
        f"      status={task['status']}  文件={s['document_count']}  字段={s['field_count']}"
        f"  品名={len(task.get('items', []))}"
        f"  冲突={s['conflict_count']}  缺失={s['missing_count']}"
        f"  未识别={s['unrecognized_count']}  风险={s['risk_count']}"
    )
    for item in task.get("items", []):
        print(f"      品名 {item['item_id']:<8} {item['display_name'][:26]}")
    for c in task["comparisons"]:
        if c["status"] != "MATCH":
            scope = "票级" if c.get("item_id") is None else f"品名 {c.get('item_id')}"
            print(f"      [{c['status']:<15}] {scope:<10} {c['label']}：{c.get('note') or ''}")
    for r in task["risks"]:
        rid = r["rule_id"] or "未经规则校验"
        print(f"      风险 {r['type']:<20} {rid}  {r['title']}")
    for e in task["errors"]:
        print(f"      错误 {e['code']:<22} {e['message']}")


def run_validator(node: str, extra: list[str], title: str) -> bool:
    print(f"\n== {title} ==")
    proc = subprocess.run(
        [node, "tools/validate_outputs.mjs", str(OUT_DIR), *extra],
        cwd=str(BACKEND_DIR),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # 抓回来自己打印：不然 node 的输出会和 Python 的缓冲输出交错，看不出哪遍是哪遍
    print((proc.stdout or "").rstrip())
    if proc.returncode != 0:
        print((proc.stderr or "").rstrip()[:2000])
        print("\n提示：若报 'Cannot find package ajv'，先在仓库根目录执行 npm install。")
    return proc.returncode == 0


def main() -> int:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    client = TestClient(app)
    print("== 打接口 ==")
    ok = True
    for name, country, country_name in CASES:
        if not (SAMPLES_DIR / name).is_dir():
            print(f"  ⚠ 跳过 {name}：样目录不存在（先运行 python tools/make_samples.py）")
            continue
        task = post_case(client, name, country, country_name)
        if not task:
            ok = False
            continue
        for comparison in task["comparisons"]:
            if comparison["status"] in {"CONFLICT", "MISSING_IN_SOME", "NOT_CHECKED"} and not comparison.get("suggested_action"):
                print(f"  ❌ {name} 的 {comparison['comparison_id']} 缺少处理建议")
                ok = False
            if comparison["status"] in {"MATCH", "SINGLE_SOURCE"} and comparison.get("suggested_action") is not None:
                print(f"  ❌ {name} 的 {comparison['comparison_id']} 不应给处理建议")
                ok = False
        for error in task["errors"]:
            if error["code"] == "DOC_PARSE_FAILED" and "建议：" not in error["message"]:
                print(f"  ❌ {name} 的解析失败缺少操作提示")
                ok = False
        if name == "08_de_bilingual_format":
            descriptions = [c for c in task["comparisons"] if c["field_key"] == "description" and c.get("item_id")]
            dates = [c for c in task["comparisons"] if c["field_key"] == "shipment_date"]
            bilingual_ok = (
                len(task["items"]) == 4
                and len(descriptions) == 4
                and all(c["status"] == "MATCH" for c in descriptions)
                and len(dates) == 1 and dates[0]["status"] == "MATCH"
                and {v["raw_value"] for v in dates[0]["values"]} == {"2026-10-10", "2026/10/10"}
                and task["summary"]["conflict_count"] == 0
                and task["summary"]["missing_count"] == 0
            )
            if not bilingual_ok:
                print("  ❌ 双语与格式差异样例未达到预期")
                ok = False
        (OUT_DIR / f"{name}.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        brief(name, task)

    # 顺带验证评测接口
    resp = client.get("/api/v1/evaluation/latest")
    (OUT_DIR / "evaluation.json").write_text(
        json.dumps(resp.json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  · /api/v1/evaluation/latest  -> {resp.json()['status']}")

    print(f"\n返回体已写入 {OUT_DIR}")

    if "--no-node" in sys.argv:
        return 0 if ok else 1

    node = find_node()
    if node is None:
        print("\n未找到 node，跳过契约校验。安装 Node.js 后运行：")
        print("  node tools/validate_outputs.mjs")
        return 0 if ok else 1

    checks = [run_validator(node, [], "按当前 CheckTask Schema 校验对外返回")]

    print()
    if ok and all(checks):
        print("✅ 自检通过：接口可跑 + 结构合法 + 计数自洽 + 引用完整")
        return 0
    print("❌ 自检未通过，见上")
    return 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
