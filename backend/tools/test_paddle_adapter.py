"""OCR table adapter guards; runs without downloading Paddle models."""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.paddle_reader import (  # noqa: E402
    _check_descriptions,
    _sequential_packing_table,
    _table_lines,
    read_image,
)
from app.pipeline.rows import parse_line_items  # noqa: E402
from app.pipeline.runner import _apply_ocr_corrections  # noqa: E402
from app.pipeline.compare import build_item_comparisons  # noqa: E402


def read_with_models(header, ordinary_rows, tables):
    """固定两路模型输出，验证真实适配逻辑；CI 不安装模型或 numpy。"""
    from PIL import Image

    data = BytesIO()
    Image.new("RGB", (10, 10), "white").save(data, format="PNG")
    lines = ["COMMERCIAL INVOICE", "INVOICE NO: INV-REVIEW-001", *header]
    lines += [cell for row in ordinary_rows for cell in row]
    lines += ["TOTAL PACKAGES: 30 CTNS"]
    markdown = "\n".join(
        "<table>" + "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for row in [header, *rows]
        ) + "</table>"
        for rows in tables
    )
    ocr = SimpleNamespace(predict=lambda **_: [SimpleNamespace(json={"res": {"rec_texts": lines}})])
    structure = SimpleNamespace(predict=lambda **_: [SimpleNamespace(markdown={"markdown_texts": markdown})])
    with patch.dict(sys.modules, {"numpy": SimpleNamespace(asarray=lambda image: image)}), \
         patch("app.pipeline.paddle_reader._get_ocr", return_value=ocr), \
         patch("app.pipeline.paddle_reader._get_structure", return_value=structure):
        return read_image(data.getvalue())


class ReviewRegressions(unittest.TestCase):
    def test_header_aliases_preserve_product_rows(self):
        for header in (
            ["NO", "ITEM NO", "DESCRIPTION", "QTY", "PACKAGES"],
            ["序号", "货号", "品名", "数量", "件数"],
        ):
            with self.subTest(header=header):
                rows = [["1", "SKU-001", "CERAMIC MUG WHITE", "100 PCS", "10 CTNS"],
                        ["2", "SKU-002", "GLASS BOTTLE BLUE", "200 PCS", "20 CTNS"]]
                result = read_with_models(header, rows, [rows])
                self.assertTrue(result.ok, result.error_message)
                table = parse_line_items(result.text)
                self.assertFalse(table.suspected)
                self.assertEqual(len(table.line_items), 2)
                descriptions = [next(f["raw_value"] for f in row["fields"]
                                     if f["field_key"] == "description") for row in table.line_items]
                self.assertEqual(descriptions, ["CERAMIC MUG WHITE", "GLASS BOTTLE BLUE"])

    def test_multiple_tables_fail_instead_of_discarding_rows(self):
        header = ["NO.", "ITEM NO.", "DESCRIPTION", "QTY", "PACKAGES"]
        first = ["1", "SKU-001", "CERAMIC MUG WHITE", "100 PCS", "10 CTNS"]
        second = ["2", "SKU-002", "GLASS BOTTLE BLUE", "200 PCS", "20 CTNS"]
        result = read_with_models(header, [first, header, second], [[first], [second]])
        self.assertTrue(result.failed)
        self.assertIn("唯一", result.error_message)
        self.assertEqual(result.text, "")

    def test_missing_item_code_does_not_hide_ocr_disagreement(self):
        for number in ("NO.", "NO"):
            with self.subTest(number=number):
                header = [number, "DESCRIPTION", "QTY", "PACKAGES"]
                ordinary = ["1", "CERAMIC MUG BLUE", "100 PCS", "10 CTNS"]
                structured = ["1", "CERAMIC MUG WHITE", "100 PCS", "10 CTNS"]
                result = read_with_models(header, [ordinary], [[structured]])
                self.assertTrue(result.failed)
                self.assertIn("货号", result.error_message)
                self.assertEqual(result.text, "")

    def test_long_description_retains_correction_evidence_and_warning(self):
        original = ("CERAMIC MUG 35OML WHITE GLAZE WITH LID AND HANDLE FOR "
                    "HOUSEHOLD DINING KITCHEN RESTAURANT HOTEL SERVICE")
        corrected = original.replace("35OML", "350ML")
        rows, uncertain, corrections = _check_descriptions(
            ["NO.   ITEM NO.   DESCRIPTION   QTY", f"1   SKU-001   {original}   100 PCS"],
            ["SKU-001", corrected],
        )
        self.assertEqual(uncertain, [])
        extracted = parse_line_items("\n".join(rows)).line_items
        clean = parse_line_items("\n".join(rows)).line_items
        _apply_ocr_corrections(extracted, corrections)
        description = next(f for f in extracted[0]["fields"] if f["field_key"] == "description")
        self.assertEqual(description["status"], "LOW_CONFIDENCE")
        self.assertEqual(description["raw_text"], original)
        self.assertEqual(description["raw_value"], original)
        documents = [{"file_id": f, "file_name": f, "process_status": "EXTRACTED"} for f in ("f1", "f2")]
        extractions = [{"file_id": f, "line_items": lines} for f, lines in (("f1", extracted), ("f2", clean))]
        items = [{"item_id": "itm_1", "alignment_status": "ALIGNED", "members": [
            {"file_id": "f1", "item_no": 1}, {"file_id": "f2", "item_no": 1},
        ]}]
        comparison = next(c for c in build_item_comparisons(items, documents, extractions, lambda *_: True)
                          if c["field_key"] == "description")
        self.assertEqual((comparison["status"], comparison["severity"]), ("MATCH", "WARNING"))
        self.assertIn("核对原件", comparison["note"])


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
    unittest.main()
