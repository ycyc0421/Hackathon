"""Regression probe for a missing required quantity in a structured JSON item row."""
import argparse
import copy
import json
from pathlib import Path
import sys

cli = argparse.ArgumentParser()
cli.add_argument("--repo", type=Path, required=True)
cli.add_argument("--out", type=Path, required=True)
args = cli.parse_args()
sys.path.insert(0, str(args.repo / "backend"))
from app.pipeline.trade_json import parse_trade_json, FORMAT
from app.pipeline.align import align_items
from app.pipeline.compare import build_item_comparisons

first = {"format": FORMAT, "doc_type": "COMMERCIAL_INVOICE", "fields": {"invoice_no": "INV-001", "currency": "USD", "total_amount": "30.00"}, "line_items": [
    {"item_no": 1, "fields": {"item_code": "SKU-A1", "description": "CERAMIC MUG BLUE", "quantity": "100 PCS"}},
    {"item_no": 2, "fields": {"item_code": "SKU-B2", "description": "GLASS CUP WHITE", "quantity": "200 PCS"}},
]}
second = copy.deepcopy(first)
second["doc_type"] = "PACKING_LIST"
second["fields"] = {"packages": "1 CARTON", "gross_weight": "10 KGS"}
second["line_items"][1]["fields"].pop("quantity")
docs, extractions = [], []
for index, obj in enumerate([first, second], 1):
    parsed = parse_trade_json(json.dumps(obj).encode())
    parsed["file_id"] = f"f{index}"
    extractions.append(parsed)
    docs.append({"file_id": f"f{index}", "file_name": f"{index}.json", "doc_type": obj["doc_type"], "process_status": "EXTRACTED"})
items = align_items(extractions, docs)
comparisons = build_item_comparisons(items, docs, extractions, lambda country, hs: False)
second_quantity = next(c for c in comparisons if c["field_key"] == "quantity" and c["item_id"] == items[1]["item_id"])
result = {"input_files": [first, second], "extractions": extractions, "items": items, "comparisons": comparisons,
          "expected": "PL SKU-B2 quantity=MISSING_IN_DOC; comparison=MISSING_IN_SOME",
          "actual": second_quantity, "bug_reproduced": second_quantity["status"] == "SINGLE_SOURCE"}
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"bug_reproduced": result["bug_reproduced"], "actual_status": second_quantity["status"], "expected_status": "MISSING_IN_SOME"}))
