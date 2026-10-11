"""OCR table adapter guards; runs without downloading Paddle models."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.paddle_reader import (  # noqa: E402
    _check_descriptions,
    _sequential_packing_table,
    _table_lines,
)
from app.pipeline.rows import parse_line_items  # noqa: E402
from app.pipeline.runner import _apply_ocr_corrections  # noqa: E402
from app.pipeline.compare import build_item_comparisons  # noqa: E402


def main() -> None:
    html = "<table><tr><td>NO.</td><td>ITEM NO.</td><td>DESCRIPTION</td><td></td><td>QTY</td></tr><tr><td>1</td><td>YT-M001</td><td>陶瓷餐具16PC蓝</td><td></td><td>1800 PCS</td></tr></table>"
    rows = _table_lines(html)
    assert rows == ["NO.   ITEM NO.   DESCRIPTION   QTY", "1   YT-M001   陶瓷餐具16PC蓝   1800 PCS"]
    try:
        _table_lines(html.replace('<td></td>', '<td colspan="2"></td>'))
    except ValueError:
        pass
    else:
        raise AssertionError("Merged table cell was accepted")
    merged, uncertain, corrections = _check_descriptions(rows, ["YT-M001", "陶瓷餐具 16PC 蓝"])
    assert merged[1] == "1   YT-M001   陶瓷餐具 16PC 蓝   1800 PCS"
    assert uncertain == []
    assert corrections == []

    _, uncertain, _ = _check_descriptions(rows, ["YT-M001", "CERAMIC TABLEWARE 16PC BLUE"])
    assert uncertain == ["YT-M001"]

    typo = ["NO.   ITEM NO.   DESCRIPTION   QTY", "1   YT-M001   CERAMIC MUG 35OML WHITE   2400 PCS"]
    corrected, uncertain, corrections = _check_descriptions(typo, ["YT-M001", "CERAMIC MUG 350ML WHITE"])
    assert "350ML" in corrected[1] and uncertain == [] and len(corrections) == 1
    assert corrections[0] == {"item_code": "YT-M001", "original": "CERAMIC MUG 35OML WHITE", "corrected": "CERAMIC MUG 350ML WHITE"}
    extracted = parse_line_items("\n".join(corrected))
    _apply_ocr_corrections(extracted.line_items, corrections)
    description = next(f for f in extracted.line_items[0]["fields"] if f["field_key"] == "description")
    assert description["raw_text"] == "CERAMIC MUG 35OML WHITE"
    assert description["raw_value"] == "CERAMIC MUG 35OML WHITE"
    assert description["status"] == "LOW_CONFIDENCE"
    assert description["normalized_value"] is not None
    clean = parse_line_items("\n".join(corrected)).line_items[0]
    documents = [
        {"file_id": "f1", "file_name": "OCR.png", "process_status": "EXTRACTED"},
        {"file_id": "f2", "file_name": "invoice.pdf", "process_status": "EXTRACTED"},
    ]
    extractions = [
        {"file_id": "f1", "line_items": extracted.line_items},
        {"file_id": "f2", "line_items": [clean]},
    ]
    items = [{"item_id": "itm_1", "alignment_status": "ALIGNED", "members": [
        {"file_id": "f1", "item_no": 1}, {"file_id": "f2", "item_no": 1},
    ]}]
    comparisons = build_item_comparisons(items, documents, extractions, lambda *_: True)
    compared = next(c for c in comparisons if c["field_key"] == "description")
    assert compared["status"] == "MATCH" and compared["severity"] == "WARNING"
    assert "OCR" in compared["note"]
    assert compared["values"][0]["raw_value"] == "CERAMIC MUG 35OML WHITE"
    _, uncertain, corrections = _check_descriptions(typo, ["YT-M001", "CERAMIC MUG 350ML BLUE"])
    assert uncertain == ["YT-M001"] and corrections == []

    plain = ["NO.", "ITEM NO.", "DESCRIPTION", "QTY", "PACKAGES", "G.W.", "1", "YT-M001", "CERAMIC MUG 350ML WHITE", "2400 PCS", "30", "CTNS", "600.00", "TOTAL PACKAGES: 30 CTNS"]
    fallback = _sequential_packing_table(plain)
    assert fallback[1] == "1   YT-M001   CERAMIC MUG 350ML WHITE   2400 PCS   30 CTNS   600.00"
    try:
        _sequential_packing_table(plain[:-2] + ["UNKNOWN", plain[-1]])
    except ValueError:
        pass
    else:
        raise AssertionError("Uncertain table cell was accepted")
    print("OCR table adapter guards passed")


if __name__ == "__main__":
    main()
