"""Read-only source audit on pinned code, using supplied PDFs and saved OCR output."""
import argparse
import ast
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

cli = argparse.ArgumentParser()
cli.add_argument("--repo", type=Path, required=True)
cli.add_argument("--out", type=Path, required=True)
cli.add_argument("--inputs", type=Path, default=Path(__file__).resolve().parent / "inputs/SHP-00002")
cli.add_argument("--ocr-output", type=Path, default=Path(__file__).resolve().parent / "evidence/ocr-reference")
args = cli.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
os.environ["PADDLE_OCR_ENABLED"] = "0"
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""
sys.path.insert(0, str(args.repo / "backend"))
sys.stdout.reconfigure(encoding="utf-8")
from app.pipeline.reader import read_document
from app.pipeline.classify import classify
from app.pipeline.rows import parse_line_items, HEADER_MAP, _looks_like_header
from app.pipeline.extract import extract_fields
from app.pipeline.align import align_items
from app.pipeline.compare import build_comparisons, build_item_comparisons

commit = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", "HEAD"], text=True).strip()
documents, extractions, files = [], [], []
for index, path in enumerate(sorted(args.inputs.glob("*.pdf")), 1):
    file_id = f"f{index}"
    result = read_document(path.name, path.read_bytes())
    assert result.parse_method.value == "TEXT_LAYER", "Expected a text-only reading path"
    doc_type = classify(result.text, path.name)
    table = parse_line_items(result.text, page=1)
    fields = extract_fields(table.doc_text, doc_type, page=1, row_keys=table.header_keys or None)
    (args.out / (path.stem + ".text-layer.txt")).write_text(result.text, encoding="utf-8")
    documents.append({"file_id": file_id, "file_name": path.name, "file_type": "PDF", "doc_type": doc_type,
                      "process_status": "EXTRACTED", "page_count": 1, "error_message": None})
    extractions.append({"file_id": file_id, "doc_type": doc_type, "parse_method": "TEXT_LAYER",
                        "fields": fields, "line_items": table.line_items})
    table_info = asdict(table)
    table_info["header_keys"] = sorted(table_info["header_keys"])
    files.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "read_method": "TEXT_LAYER", "table": table_info, "fields": fields})

items = align_items(extractions, documents)
comparisons = build_comparisons(documents, extractions, lambda country, code: False, destination_country="US")
comparisons += build_item_comparisons(items, documents, extractions, lambda country, code: False,
                                     destination_country="US", start_index=len(comparisons))

adapter_path = args.repo / "backend/app/pipeline/paddle_reader.py"
tree = ast.parse(adapter_path.read_text(encoding="utf-8"))
selected = [x for x in tree.body if isinstance(x, (ast.FunctionDef, ast.ClassDef)) and x.name in
            {"_TableParser", "_table_lines", "_header_key", "_table_start"}]
scope = {"HTMLParser": HTMLParser, "HEADER_MAP": HEADER_MAP, "_looks_like_header": _looks_like_header}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(adapter_path), "exec"), scope)
probe_inputs = {
    "ordinary": '<table><tr><td>SKU</td><td>QTY</td></tr><tr><td>SKU-A1</td><td>500</td></tr></table>',
    "valid_colspan": '<table><tr><td colspan="2">INVOICE</td></tr><tr><td>SKU</td><td>QTY</td></tr><tr><td>SKU-A1</td><td>500</td></tr></table>',
    "actual_correct_vl_output": next((args.ocr_output / "paddleocr-vl-bf16/packing_list").glob("*.md")).read_text(encoding="utf-8"),
}
probes = {}
for name, html in probe_inputs.items():
    try:
        probes[name] = {"result": scope["_table_lines"](html)}
    except Exception as error:
        probes[name] = {"error": str(error)}
raw_ocr = (args.ocr_output / "classic-paddleocr/packing_list.raw-text.txt").read_text(encoding="utf-8")
probes["actual_ocr_header_detection"] = {"table_start": scope["_table_start"](raw_ocr.splitlines())}

source_map = {}
for filename in ["reader.py", "rows.py", "extract.py", "paddle_reader.py", "compare.py", "runner.py"]:
    path = args.repo / "backend/app/pipeline" / filename
    body = path.read_text(encoding="utf-8")
    functions = {n.name: {"start": n.lineno, "end": n.end_lineno} for n in ast.walk(ast.parse(body)) if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    source_map[filename] = {"sha256_lf": hashlib.sha256(body.replace("\r\n", "\n").encode()).hexdigest(), "functions": functions}

output = {"commit": commit, "source_repo": str(args.repo), "ocr_invoked": False,
          "files": files, "documents": documents, "extractions": extractions,
          "items": items, "comparisons": comparisons, "adapter_probes": probes, "source_map": source_map,
          "summary": {"items": len(items), "comparisons": len(comparisons),
                      "conflicts": sum(c["status"] == "CONFLICT" for c in comparisons),
                      "unrecognized": sum(c["status"] == "UNRECOGNIZED" for c in comparisons)}}
(args.out / "root-cause-results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"commit": commit, "summary": output["summary"], "adapter": probes}, ensure_ascii=False))
