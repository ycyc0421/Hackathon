"""审查边界：结构合法但语义不能伪造 MATCH / COMPLETED。"""

from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.doc_profile import expects
from app.pipeline.align import Row, _mutually_unique, align_items
from app.pipeline.compare import _agree, build_item_comparisons
from app.pipeline.extract import _m_packages, extract_fields
from app.pipeline.normalize import to_measure
from app.pipeline.reader import ReadResult, _read_pdf
from app.pipeline.rows import parse_line_items
from app.models import ParseMethod


def value(table, key):
    return next(f for f in table.line_items[0]["fields"] if f["field_key"] == key)


class ReviewRegressions(unittest.TestCase):
    def test_ambiguous_item_codes(self) -> None:
        header = "NO.  ITEM NO.  DESCRIPTION  QTY  PACKAGES\n"
        white = "SKU-001  CERAMIC MUG WHITE  100 PCS  10 CARTONS"
        black = "SKU-001  CERAMIC MUG BLACK  200 PCS  20 CARTONS"
        a = parse_line_items(header + f"1  {white}\n2  {black}\nTOTAL 300 PCS")
        b = parse_line_items(header + f"1  {black}\n2  {white}\nTOTAL 300 PCS")
        assert not a.suspected and not b.suspected
        docs = [{"file_id": f, "file_name": f, "process_status": "EXTRACTED"} for f in ("f1", "f2")]
        exts = [{"file_id": f, "line_items": t.line_items, "fields": []} for f, t in (("f1", a), ("f2", b))]
        items = align_items(exts, docs)
        assert len(items) == 2 and all(i["alignment_status"] == "UNALIGNED" for i in items), items
        assert sum(len(i["members"]) for i in items) == 4
        assert all(m["match_score"] is None for i in items for m in i["members"])
        comparisons = build_item_comparisons(items, docs, exts, lambda *_: True, "DE", "德国")
        assert comparisons and all(c["status"] == "NOT_CHECKED" for c in comparisons), comparisons
        single_source = align_items(exts[:1], docs[:1])
        assert len(single_source) == 2 and all(i["alignment_status"] == "PARTIAL" for i in single_source)

    def test_incomplete_table(self) -> None:
        header = "NO.  DESCRIPTION  QTY  PACKAGES\n"
        first = "1  CERAMIC MUG  100 PCS  10 CARTONS\n"
        mixed = parse_line_items(header + first + "GLASS BOTTLES 500 PCS 20 CARTONS\nTOTAL 600 PCS")
        assert mixed.suspected, mixed
        repeated = parse_line_items(header + first + "1  GLASS BOTTLES  500 PCS  20 CARTONS\nTOTAL 600 PCS")
        assert repeated.suspected, repeated
        full = "".join(f"{i}  CERAMIC MUG  1 PCS  1 CARTON\n" for i in range(1, 201))
        assert not parse_line_items(header + full + "TOTAL 200 PCS").suspected
        over_limit = parse_line_items(header + full + "201  GLASS BOTTLES  500 PCS  20 CARTONS\nTOTAL 700 PCS")
        assert over_limit.suspected, over_limit
        valid = parse_line_items(header + first + "2  GLASS BOTTLES  500 PCS  20 CARTONS\nTOTAL 600 PCS")
        assert not valid.suspected and len(valid.line_items) == 2, valid
        footer = parse_line_items(header + first + "总件数: 10 箱\n毛重: 100 公斤")
        assert not footer.suspected and len(footer.line_items) == 1, footer
        assert "总件数: 10 箱" in footer.doc_text and "毛重: 100 公斤" in footer.doc_text, footer

    def test_package_units(self) -> None:
        for text, unit in (
            ("SAY TEN (10) PALLETS ONLY", "PALLETS"),
            ("PACKAGES: 10 CRATES", "CRATES"),
            ("PACKAGES: 10  CARTONS (PALLETS)", "PALLETS"),
            ("PACKAGES: 10\nG.W.: 100 KGS", None),
        ):
            field = next(f for f in extract_fields(text, "PACKING_LIST") if f["field_key"] == "packages")
            if unit:
                assert unit in field["raw_value"], field
                assert field["status"] == "NORMALIZE_FAILED", field
                assert field["normalized_value"] is None and field["unit"] is None, field
            else:
                assert field["normalized_value"] == 10 and field["unit"] is None, field
        for text in ("SAY TEN (10) CARTONS ONLY", "PACKAGES: 10  CARTONS", "件数：10 箱（CARTONS）"):
            field = next(f for f in extract_fields(text, "PACKING_LIST") if f["field_key"] == "packages")
            assert field["normalized_value"] == 10 and field["unit"] == "CARTON", field
            assert "CARTONS" in field["raw_value"], field

    def test_measure_units(self) -> None:
        for raw, key, expected in (
            ("(LBS): 100", "gross_weight", (45.359237, "KGS")),
            ("100 LBS", "net_weight", (45.359237, "KGS")),
            ("LBS 100 磅", "gross_weight", (45.359237, "KGS")),
            ("(KGS): 100", "gross_weight", (100, "KGS")),
            ("（公斤）：2.400,00 KGS", "gross_weight", (2400, "KGS")),
            ("100", "gross_weight", (100, "KGS")),
            ("(100) KGS", "gross_weight", (100, "KGS")),
            ("120 箱（CARTONS）", "packages", (120, "CARTON")),
            ("个（PCS）：20", "quantity", (20, "PCS")),
            ("M3: 2,50", "volume", (2.5, "CBM")),
            ("2.50 M3", "volume", (2.5, "CBM")),
            ("SETS 20", "quantity", (None, None)),
            ("TONNES: 100", "gross_weight", (None, None)),
            ("(LBS): 100 KGS", "gross_weight", (None, None)),
            ("100 KGS (LBS)", "gross_weight", (None, None)),
            ("UNKNOWN 100 KGS", "gross_weight", (None, None)),
            ("100 KGS 200 KGS", "gross_weight", (None, None)),
        ):
            assert to_measure(raw, key) == expected, (raw, key, to_measure(raw, key))
        for text in ("GROSS WEIGHT (LBS): 100", "G.W.: 100  LBS", "GROSS WEIGHT (LBS):  100"):
            field = next(f for f in extract_fields(text, "PACKING_LIST") if f["field_key"] == "gross_weight")
            assert field["normalized_value"] == 45.359237 and field["unit"] == "KGS", field
            assert "LBS" in field["raw_value"], field
        for text in ("QUANTITY: SETS 20", "QUANTITY: 20  PACKAGES"):
            quantity = next(f for f in extract_fields(text, "PACKING_LIST") if f["field_key"] == "quantity")
            assert quantity["status"] == "NORMALIZE_FAILED" and quantity["unit"] is None, quantity

    def test_mixed_pdf_header(self) -> None:
        from fpdf import FPDF
        from PIL import Image, ImageDraw
        from pypdf import PdfReader

        image = Image.new("RGB", (1300, 1800), "white")
        draw = ImageDraw.Draw(image)
        draw.text((60, 80), "DESCRIPTION: GLASS BOTTLES\nQUANTITY: 500 PCS\nGROSS WEIGHT: 600 KGS", fill="black")
        blob = BytesIO()
        image.save(blob, format="PNG")

        def document(large_body: bool) -> bytes:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            for line in ("COMMERCIAL INVOICE", "DESCRIPTION: CERAMIC MUG", "QUANTITY: 100 PCS", "GROSS WEIGHT: 100 KGS"):
                pdf.cell(0, 6, text=line, new_x="LMARGIN", new_y="NEXT")
            pdf.add_page()
            for line in ("COMMERCIAL INVOICE - CONTINUATION PAGE", "INVOICE NO: INV-REVIEW-001",
                         "SHIPPER: EXPORT TEST COMPANY", "CONSIGNEE: IMPORT TEST COMPANY"):
                pdf.cell(0, 6, text=line, new_x="LMARGIN", new_y="NEXT")
            # 同一张高分辨率图，按页面上的实际绘制大小区分正文和小 logo。
            pdf.image(BytesIO(blob.getvalue()), x=10, y=55, w=190 if large_body else 15, h=225 if large_body else 18)
            return bytes(pdf.output())

        data = document(True)
        assert len(PdfReader(BytesIO(data)).pages[1].extract_text().strip()) > 40
        with patch("app.pipeline.reader.llm_enabled", return_value=False):
            result = _read_pdf(data)
            assert result.failed and result.page_count == 2 and "2" in (result.error_message or ""), result
            assert result.text == "" and result.parse_method is None, result
            logo = _read_pdf(document(False))
            assert logo.ok and logo.parse_method == ParseMethod.TEXT_LAYER, logo
        images = [("image/png", b"page-one"), ("image/png", b"page-two")]
        ocr = ReadResult(text="GLASS BOTTLES 500 PCS 600 KGS", page_count=2, parse_method=ParseMethod.OCR)
        with patch("app.pipeline.reader.llm_enabled", return_value=True), \
             patch("app.pipeline.reader._pdf_pages_to_images", return_value=images) as render, \
             patch("app.pipeline.reader._transcribe_with_llm", return_value=ocr) as transcribe:
            assert _read_pdf(data) is ocr
            render.assert_called_once_with(data)
            transcribe.assert_called_once_with(images, page_count=2)
        with patch("app.pipeline.reader.llm_enabled", return_value=True), \
             patch("app.pipeline.reader._pdf_pages_to_images", return_value=None), \
             patch("app.pipeline.reader._transcribe_with_llm") as transcribe:
            assert _read_pdf(data).failed
            transcribe.assert_not_called()

    def test_pdf_image_placement(self) -> None:
        from fpdf import FPDF
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

        pdf = FPDF(unit="pt", format=(600, 800))
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(text="COMMERCIAL INVOICE - TEXT HEADER WITH SUFFICIENT CHARACTERS")
        source = bytes(pdf.output())

        def document(operations: bytes, nested: bool = False) -> bytes:
            writer = PdfWriter()
            page = writer.add_page(PdfReader(BytesIO(source)).pages[0])
            # 1×1 像素的内联图像仍可能被放大为整页正文。
            inline = b"BI /W 1 /H 1 /CS /RGB /BPC 8 ID \x00\x00\x00 EI\n"
            content = DecodedStreamObject()
            if nested:
                form = DecodedStreamObject()
                form.set_data(inline)
                form.update({
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Form"),
                    NameObject("/BBox"): ArrayObject([NumberObject(v) for v in (0, 0, 1, 1)]),
                    NameObject("/Matrix"): ArrayObject([NumberObject(v) for v in (2, 0, 0, 2, 0, 0)]),
                    NameObject("/Resources"): DictionaryObject(),
                })
                page["/Resources"][NameObject("/XObject")] = DictionaryObject({NameObject("/Body"): writer._add_object(form)})
                image = b"/Body Do\n"
            else:
                image = inline
            content.set_data(page.get_contents().get_data() + b"\n" + operations.replace(b"IMAGE", image))
            page[NameObject("/Contents")] = writer._add_object(content)
            result = BytesIO()
            writer.write(result)
            return result.getvalue()

        for operations, nested, failed in (
            (b"q 400 0 0 500 10 10 cm IMAGE Q", False, True),
            (b"q 15 0 0 18 10 10 cm IMAGE Q", False, False),
            (b"q 200 0 0 250 10 10 cm IMAGE Q", True, True),
            (b"q 7 0 0 9 10 10 cm IMAGE Q", True, False),
            (b"q 0 500 -400 0 500 10 cm IMAGE Q", False, True),
            (b"q 400 0 0 500 900 900 cm IMAGE Q", False, False),
            (b"q 400 0 0 150 10 10 cm IMAGE Q q 400 0 0 150 10 200 cm IMAGE Q", False, True),
            (b"q 400 0 0 150 10 10 cm IMAGE Q q 400 0 0 150 10 10 cm IMAGE Q", False, False),
        ):
            with patch("app.pipeline.reader.llm_enabled", return_value=False):
                result = _read_pdf(document(operations, nested))
            assert result.failed == failed, (operations, nested, result)
            if not failed:
                assert result.parse_method == ParseMethod.TEXT_LAYER, result

    def test_column_order_preserves_quantity_and_packages(self):
        a = parse_line_items("NO.  DESCRIPTION  QTY  PACKAGES\n1  CERAMIC MUG  100 PCS  10 CARTONS\nTOTAL 100 PCS")
        b = parse_line_items("NO.  DESCRIPTION  PACKAGES  QTY\n1  CERAMIC MUG  100 CARTONS  10 PCS\nTOTAL 10 PCS")
        assert value(a, "quantity")["normalized_value"] == 100
        assert value(b, "quantity")["normalized_value"] == 10
        assert value(a, "packages")["normalized_value"] == 10
        assert value(b, "packages")["normalized_value"] == 100
        docs = [{"file_id": f, "file_name": f, "process_status": "EXTRACTED"} for f in ("f1", "f2")]
        exts = [{"file_id": f, "line_items": table.line_items, "fields": []} for f, table in (("f1", a), ("f2", b))]
        items = align_items(exts, docs)
        comparisons = build_item_comparisons(items, docs, exts, lambda *_: True, "DE", "德国")
        assert next(c for c in comparisons if c["field_key"] == "quantity")["status"] == "CONFLICT"
        assert next(c for c in comparisons if c["field_key"] == "packages")["status"] == "CONFLICT"

    def test_package_and_weight_units(self):
        assert _m_packages("PACKAGES: 10 PALLETS").raw_value == "10 PALLETS"
        pounds = extract_fields("G.W.: 100 LBS", "PACKING_LIST")
        gross = next(f for f in pounds if f["field_key"] == "gross_weight")
        assert gross["raw_value"] == "100 LBS" and gross["normalized_value"] == 45.359237
        assert value(parse_line_items("NO.  DESCRIPTION  QTY  PACKAGES\n1  MUG  20 SETS  10 CARTONS\nTOTAL 20 SETS"), "quantity")["status"] == "NORMALIZE_FAILED"
        assert value(parse_line_items("NO.  DESCRIPTION  QTY  PACKAGES\n1  MUG  20 PCS  10 PALLETS\nTOTAL 20 PCS"), "packages")["status"] == "NORMALIZE_FAILED"

    def test_hs_prefix_requires_consistent_specific_codes(self):
        assert not _agree("hs_code", ["691110", "6911101000", "6911109000"])[0]
        assert _agree("hs_code", ["691110", "6911101000", "69111010"])[0]

    def test_description_alignment_is_mutually_unique(self):
        rows = [Row("f1", "invoice", 1, None, "陶瓷 马克杯 白"), Row("f1", "invoice", 2, None, "陶瓷 马克杯 白 釉"), Row("f2", "packing", 1, None, "陶瓷 马克杯 白 釉")]
        assert not _mutually_unique(rows[0], rows[2], rows)
        assert _mutually_unique(rows[1], rows[2], rows)
        def desc_field(text):
            return {"field_key": "description", "normalized_value": text, "status": "EXTRACTED"}
        ambiguous_exts = [
            {"file_id": "f1", "line_items": [
                {"item_no": 1, "fields": [desc_field(rows[0].desc)]},
                {"item_no": 2, "fields": [desc_field(rows[1].desc)]},
            ]},
            {"file_id": "f2", "line_items": [{"item_no": 1, "fields": [desc_field(rows[2].desc)]}]},
        ]
        docs = [{"file_id": f, "file_name": f, "process_status": "EXTRACTED"} for f in ("f1", "f2")]
        aligned = align_items(ambiguous_exts, docs)
        matched = [item for item in aligned if len(item["members"]) == 2]
        assert len(matched) == 1
        assert {(m["file_id"], m["item_no"]) for m in matched[0]["members"]} == {("f1", 2), ("f2", 1)}

    def test_european_decimal_in_table(self):
        euro = parse_line_items("NO.  DESCRIPTION  QTY  G.W.\n1  MUG  10 PCS  2.400,00 KGS\nTOTAL 10 PCS")
        assert value(euro, "gross_weight")["normalized_value"] == 2400

        assert not expects("COMMERCIAL_INVOICE", "packages")
        assert not expects("COMMERCIAL_INVOICE", "gross_weight")
        assert not expects("COMMERCIAL_INVOICE", "net_weight")

    def test_invoice_optional_fields(self):
        assert not expects("COMMERCIAL_INVOICE", "hs_code")
        assert expects("COMMERCIAL_INVOICE", "quantity")

    def test_mixed_pdf_cannot_hide_unread_page(self):
        from fpdf import FPDF
        from PIL import Image

        image = Image.new("RGB", (300, 100), "white")
        image_bytes = BytesIO()
        image.save(image_bytes, format="PNG")
        image_bytes.seek(0)
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(text="COMMERCIAL INVOICE TEXT LAYER " * 4)
        pdf.add_page()
        pdf.image(image_bytes, x=10, y=10, w=100)
        result = _read_pdf(bytes(pdf.output()))
        assert result.failed and result.page_count == 2 and "2" in (result.error_message or "")


if __name__ == "__main__":
    unittest.main()
