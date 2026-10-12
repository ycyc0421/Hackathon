"""Model-free causal probes against the fixed candidate, with local inputs only."""
import argparse
import ast
from dataclasses import asdict
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
cli = argparse.ArgumentParser()
cli.add_argument("--repo", type=Path, required=True)
cli.add_argument("--data", type=Path, required=True, help="New-case handoff root")
cli.add_argument("--out", type=Path, required=True)
args = cli.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
os.environ["PADDLE_OCR_ENABLED"] = "0"
for name in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
    os.environ[name] = ""
sys.path.insert(0, str(args.repo / "backend"))
from pypdf import PdfReader
from app.pipeline import rows, extract, classify, paddle_reader

def snapshot(table):
    obj = asdict(table)
    obj["header_keys"] = sorted(obj["header_keys"])
    return obj

def selected_fields(text, kind):
    return {field["field_key"]: field for field in extract.extract_fields(text, kind, page=1)
            if field["field_key"] in {"shipper", "consignee", "invoice_no", "document_no"}}

def read_pdf(group, filename):
    path = args.data / "inputs" / group / filename
    return PdfReader(BytesIO(path.read_bytes())).pages[0].extract_text(), hashlib.sha256(path.read_bytes()).hexdigest()

commit = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", "HEAD"], text=True).strip()
assert commit == "6a526985162b90a6757fa5f447ac2e976623f64e"
results = {}

# A missing PDF cell leaves 3 values for 4 numeric columns. Trace captures the exact rejection.
text, digest = read_pdf("SHP-00017", "commercial_invoice.pdf")
rejections = []
def trace(frame, event, arg):
    if frame.f_code.co_name == "_stacked_table" and event == "return" and isinstance(arg, tuple) and arg[1]:
        local = frame.f_locals
        rejections.append({"return_line": frame.f_lineno, "header_keys": local.get("keys"),
                           "position": local.get("pos"), "numeric_slice": local.get("values"),
                           "nearby_lines": local.get("lines", [])[max(0, local.get("pos", 0)-2):local.get("pos", 0)+6]})
    return trace
sys.settrace(trace)
table = rows.parse_line_items(text, page=1)
sys.settrace(None)
assert table.suspected and len(table.line_items) == 0
results["pdf_empty_cell"] = {"sha256": digest, "original_text": text, "actual": snapshot(table), "exact_rejection": rejections}

# A correct HTML grid already knows the blank column, but space serialization loses it.
def html(hs):
    return '<table><tr><td>NO.</td><td>SKU</td><td>DESCRIPTION</td><td>HS CODE</td><td>QTY</td><td>UNIT PRICE</td><td>AMOUNT</td></tr><tr><td>1</td><td>SKU-0017-1</td><td>Paper notebook</td><td>' + hs + '</td><td>200 PCS</td><td>2.27</td><td>454.00</td></tr></table>'
grid_results = {}
for name, value in [("filled", "482010"), ("empty", "")]:
    lines = paddle_reader._table_lines(html(value))
    parsed = rows.parse_line_items("\n".join(lines) + "\nTOTAL AMOUNT (GBP): 454.00", page=1)
    grid_results[name] = {"html": html(value), "adapter_lines": lines,
                          "data_cells_after_split": rows._cells(lines[1]), "parsed": snapshot(parsed)}
assert not grid_results["filled"]["parsed"]["suspected"]
assert grid_results["empty"]["parsed"]["suspected"]
assert len(grid_results["filled"]["data_cells_after_split"]) == 6
assert len(grid_results["empty"]["data_cells_after_split"]) == 5
results["html_empty_cell_loss"] = grid_results

# Identical company strings, different reading order; no OCR model is involved.
seller = "Harbor Industrial 0001 Co., Ltd."
buyer = "Aster Distribution 1001 Inc."
grouped = f"SELLER / EXPORTER\n{seller}\nBUYER / IMPORTER\n{buyer}"
interleaved = f"SELLER / EXPORTER\nBUYER / IMPORTER\n{seller}\n{buyer}"
party_variants = {name: {"input_text": value, "fields": selected_fields(value, "COMMERCIAL_INVOICE")}
                  for name, value in [("grouped", grouped), ("interleaved", interleaved)]}
assert party_variants["grouped"]["fields"]["shipper"]["raw_value"] == seller
assert party_variants["interleaved"]["fields"]["shipper"]["raw_value"] == "BUYER / IMPORTER"
assert party_variants["interleaved"]["fields"]["consignee"]["raw_value"] == seller
results["party_reading_order"] = {"variants": party_variants,
    "label_guard_rejects_buyer_label": bool(extract._OTHER_LABEL_WORDS.fullmatch("BUYER / IMPORTER"))}

# The number is present, but changing only its label makes the matcher see it.
pi_text, pi_digest = read_pdf("SHP-00011", "proforma_invoice.pdf")
actual_type = classify.classify(pi_text, "proforma_invoice.pdf")
renamed_type = classify.classify(pi_text, "opaque.pdf")
literal = "REFERENCES: CI CI-00011 | PI PI-00011 | PL PL-00011"
assert literal in pi_text
relabeled = pi_text.replace(literal, "INVOICE NO.: CI-00011")
assert extract._m_invoice_no(pi_text) is None
assert extract._m_invoice_no(relabeled).raw_value == "CI-00011"
results["invoice_reference_and_classification"] = {"sha256": pi_digest, "reference_line": literal,
    "type_with_original_filename": actual_type, "type_with_neutral_filename": renamed_type,
    "actual_fields": selected_fields(pi_text, actual_type), "fields_with_other_type": selected_fields(pi_text, "OTHER"),
    "same_number_with_supported_label": selected_fields(relabeled, actual_type)}

# Missing metadata is caused by the caller argument, not inability to identify a one-page PDF.
good_text, good_digest = read_pdf("SHP-00011", "commercial_invoice.pdf")
default_table = rows.parse_line_items(good_text)
page_table = rows.parse_line_items(good_text, page=1)
original_values = [{f["field_key"]: f["normalized_value"] for f in line["fields"]} for line in default_table.line_items]
provided_values = [{f["field_key"]: f["normalized_value"] for f in line["fields"]} for line in page_table.line_items]
assert original_values == provided_values
default_pages = [f["page"] for line in default_table.line_items for f in line["fields"] if f["normalized_value"] is not None]
provided_pages = [f["page"] for line in page_table.line_items for f in line["fields"] if f["normalized_value"] is not None]
assert default_pages and all(page is None for page in default_pages)
assert all(page == 1 for page in provided_pages)
results["page_argument"] = {"sha256": good_digest, "values_unchanged": True,
                            "pages_with_default_argument": default_pages, "pages_with_explicit_argument": provided_pages}

# Retain the exact structured description, while varying only its location in ordinary text.
traces = args.data / "evidence/scan-warm-1/ocr-traces"
ordinary = (traces / "ordinary-1-0.txt").read_text(encoding="utf-8").splitlines()
markdown = (traces / "structure-1-0.md").read_text(encoding="utf-8")
model_table = paddle_reader._table_lines(markdown)
header = model_table[0].split("   ")
code_at = next(i for i, cell in enumerate(header) if paddle_reader._header_key(cell) == "item_code")
desc_at = next(i for i, cell in enumerate(header) if paddle_reader._header_key(cell) == "description")
cells = model_table[1].split("   ")
code, description = cells[code_at], cells[desc_at]
where = next(i for i, cell in enumerate(ordinary) if cell.strip().upper() == code.upper())
actual_check = paddle_reader._check_descriptions(model_table, ordinary)
correct_pair = paddle_reader._check_descriptions(model_table, [code, description])
wrong_pair = paddle_reader._check_descriptions(model_table, [code, "TOTAL AMOUNT (USD): 922.08"])
assert actual_check[1] == [code] and correct_pair[1] == [] and wrong_pair[1] == [code]
results["description_lookup"] = {"sku": code, "structured_description": description,
    "actual_next_line": ordinary[where + 1], "actual_uncertain_codes": actual_check[1],
    "same_description_after_sku_uncertain_codes": correct_pair[1], "total_after_sku_uncertain_codes": wrong_pair[1]}

source_map = {}
for name in ["rows.py", "extract.py", "classify.py", "paddle_reader.py", "runner.py", "compare.py", "rules.py"]:
    path = args.repo / "backend/app/pipeline" / name
    body = path.read_text(encoding="utf-8")
    nodes = ast.parse(body)
    source_map[name] = {"sha256_lf": hashlib.sha256(body.replace("\r\n", "\n").encode()).hexdigest(),
        "functions": {node.name: {"start": node.lineno, "end": node.end_lineno} for node in ast.walk(nodes)
                      if isinstance(node, (ast.FunctionDef, ast.ClassDef))}}
output = {"commit": commit, "model_invoked": False, "production_accessed": False,
          "source_files_modified": False, "controlled_inputs_are_diagnostic_only": True,
          "probes": results, "source_map": source_map}
(args.out / "causal-probes.json").write_bytes((json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
print(json.dumps({"commit": commit, "probes_passed": list(results), "exact_pdf_rejection": rejections,
                  "actual_type": actual_type, "neutral_filename_type": renamed_type,
                  "actual_description_lookup": ordinary[where + 1], "model_invoked": False}, ensure_ascii=False))
