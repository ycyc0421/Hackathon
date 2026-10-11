"""审查边界：结构合法但语义不能伪造 MATCH / COMPLETED。"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.doc_profile import expects
from app.pipeline.align import Row, _mutually_unique, align_items
from app.pipeline.compare import _agree, build_item_comparisons
from app.pipeline.extract import _m_packages, extract_fields
from app.pipeline.reader import _read_pdf
from app.pipeline.rows import parse_line_items


def value(table, key):
    return next(f for f in table.line_items[0]["fields"] if f["field_key"] == key)


def main() -> None:
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

    assert _m_packages("PACKAGES: 10 PALLETS").raw_value == "10 PALLETS"
    pounds = extract_fields("G.W.: 100 LBS", "PACKING_LIST")
    gross = next(f for f in pounds if f["field_key"] == "gross_weight")
    assert gross["raw_value"] == "100 LBS" and gross["normalized_value"] == 45.359237
    assert value(parse_line_items("NO.  DESCRIPTION  QTY  PACKAGES\n1  MUG  20 SETS  10 CARTONS\nTOTAL 20 SETS"), "quantity")["status"] == "NORMALIZE_FAILED"
    assert value(parse_line_items("NO.  DESCRIPTION  QTY  PACKAGES\n1  MUG  20 PCS  10 PALLETS\nTOTAL 20 PCS"), "packages")["status"] == "NORMALIZE_FAILED"

    assert not _agree("hs_code", ["691110", "6911101000", "6911109000"])[0]
    assert _agree("hs_code", ["691110", "6911101000", "69111010"])[0]

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
    aligned = align_items(ambiguous_exts, docs)
    matched = [item for item in aligned if len(item["members"]) == 2]
    assert len(matched) == 1
    assert {(m["file_id"], m["item_no"]) for m in matched[0]["members"]} == {("f1", 2), ("f2", 1)}

    euro = parse_line_items("NO.  DESCRIPTION  QTY  G.W.\n1  MUG  10 PCS  2.400,00 KGS\nTOTAL 10 PCS")
    assert value(euro, "gross_weight")["normalized_value"] == 2400

    assert not expects("COMMERCIAL_INVOICE", "packages")
    assert not expects("COMMERCIAL_INVOICE", "gross_weight")
    assert not expects("COMMERCIAL_INVOICE", "net_weight")
    assert not expects("COMMERCIAL_INVOICE", "hs_code")
    assert expects("COMMERCIAL_INVOICE", "quantity")

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
    print("审查边界回归通过（列序、单位、HS、行对齐、欧式小数、字段规则、混合 PDF）")


if __name__ == "__main__":
    main()
