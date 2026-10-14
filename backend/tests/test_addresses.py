"""Address extraction and strict cross-document comparison regressions.

The optional PDF regression reads original files in HACKATHON_ADDRESS_DATASET;
it never copies or edits them and never calls an external OCR/model endpoint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import classify, reader
from app.pipeline.compare import build_comparisons
from app.pipeline.extract import extract_fields
from app.pipeline.rows import TableResult, parse_line_items
from app.pipeline.runner import _locate_document_pages


SHIPPER = "Example Export Co., Ltd."
CONSIGNEE = "Example Import Inc."
SELLER_ADDRESS = "24 Harbor Road, Suite 17\nNingbo, Zhejiang 315000, China"
BUYER_ADDRESS = "742 Garden Street, Suite 36\nSeattle, WA 98101, United States"
ADDRESS_KEYS = ("shipper_address", "consignee_address")


def block_document(buyer_address=BUYER_ADDRESS, seller_address=SELLER_ADDRESS):
    return (
        "COMMERCIAL INVOICE\nDocument No.: CI-TEST-1\n"
        f"SELLER / EXPORTER\n{SHIPPER}\n{seller_address}\n"
        "Email: seller@example.test\nTel: +86 574 1234567 | Contact Person\n"
        f"BUYER / IMPORTER\n{CONSIGNEE}\n{buyer_address}\n"
        "Email: buyer@example.test\nTel: +1 206 1234567 | Other Contact\n"
        "INCOTERM\nFOB Ningbo\nTOTAL AMOUNT (USD): 1400.00\n"
    )


def extracted(text, page=1):
    return {f["field_key"]: f for f in extract_fields(text, "COMMERCIAL_INVOICE", page=page)}


def document(file_id, doc_type="COMMERCIAL_INVOICE"):
    return {
        "file_id": file_id,
        "file_name": f"{file_id}.pdf",
        "file_type": "PDF",
        "doc_type": doc_type,
        "process_status": "EXTRACTED",
        "page_count": 1,
        "error_message": None,
    }


def compare_texts(*texts):
    docs = [document(f"file-{i}") for i in range(len(texts))]
    exts = [{"file_id": d["file_id"], "doc_type": d["doc_type"],
             "parse_method": "TEXT_LAYER",
             "fields": list(extracted(text).values())}
            for d, text in zip(docs, texts)]
    return {c["field_key"]: c for c in build_comparisons(docs, exts, lambda *_: False)}


def assert_no_usable_address(fields):
    for key in ADDRESS_KEYS:
        field = fields.get(key)
        assert field is None or field["status"] not in {"EXTRACTED", "LOW_CONFIDENCE"}, field
        if field is not None:
            assert field["normalized_value"] is None, field


def test_party_addresses_are_separate_from_company_and_contacts():
    text = block_document()
    fields = extracted(text, page=4)
    assert fields["shipper"]["raw_value"] == SHIPPER
    assert fields["consignee"]["raw_value"] == CONSIGNEE
    for key, address in zip(ADDRESS_KEYS, (SELLER_ADDRESS, BUYER_ADDRESS)):
        field = fields[key]
        assert field["status"] == "EXTRACTED", field
        assert field["raw_value"] == address
        assert all(line in field["raw_text"] for line in address.splitlines())
        assert "Email:" not in field["raw_value"]
        assert "Tel:" not in field["raw_value"]
        assert field["page"] == 4
        assert field["confidence"] is None
        assert field["bbox"] is None


@pytest.mark.parametrize("label", ["SHIPPER ADDRESS", "SELLER ADDRESS", "发货人地址", "卖方地址"])
def test_explicit_shipper_address_label(label):
    fields = extracted(f"COMMERCIAL INVOICE\nSHIPPER: {SHIPPER}\n{label}: {SELLER_ADDRESS}\nTel: +86 574 1234567")
    field = fields["shipper_address"]
    assert field["status"] == "EXTRACTED", field
    assert field["raw_value"] == SELLER_ADDRESS
    assert label in field["raw_text"]


@pytest.mark.parametrize("label", ["CONSIGNEE ADDRESS", "BUYER ADDRESS", "收货人地址", "买方地址"])
def test_explicit_consignee_address_label(label):
    fields = extracted(f"COMMERCIAL INVOICE\nCONSIGNEE: {CONSIGNEE}\n{label}: {BUYER_ADDRESS}\nEmail: buyer@example.test")
    field = fields["consignee_address"]
    assert field["status"] == "EXTRACTED", field
    assert field["raw_value"] == BUYER_ADDRESS


@pytest.mark.parametrize("changed", [
    "743 Garden Street, Suite 36\nSeattle, WA 98101, United States",
    "742 Market Street, Suite 36\nSeattle, WA 98101, United States",
    "742 Garden Street, Suite 37\nSeattle, WA 98101, United States",
    "742 Garden Street, Suite 36\nSeattle, WA 98102, United States",
])
def test_small_address_changes_conflict_without_fuzzy_match(changed):
    comparisons = compare_texts(block_document(), block_document(buyer_address=changed))
    address = comparisons["consignee_address"]
    assert address["status"] == "CONFLICT", address
    assert address["value_type"] == "STRING"
    assert address["canonical_value"] is None
    assert {v["file_id"] for v in address["values"]} == {"file-0", "file-1"}
    assert all(v["page"] == 1 for v in address["values"])
    assert comparisons["shipper_address"]["status"] == "MATCH"
    assert comparisons["shipper"]["status"] == "MATCH"
    assert comparisons["consignee"]["status"] == "MATCH"


def test_case_and_whitespace_only_address_variation_matches():
    changed = "  742 garden street,   suite 36\n Seattle, WA 98101, united states  "
    comparisons = compare_texts(block_document(), block_document(buyer_address=changed))
    assert comparisons["consignee_address"]["status"] == "MATCH"


def test_address_token_order_is_significant():
    changed = "36 Garden Street, Suite 742\nSeattle, WA 98101, United States"
    comparisons = compare_texts(block_document(), block_document(buyer_address=changed))
    assert comparisons["consignee_address"]["status"] == "CONFLICT"


def test_company_change_does_not_change_matching_address():
    text = block_document().replace(CONSIGNEE, "Another Import Inc.")
    comparisons = compare_texts(block_document(), text)
    assert comparisons["consignee"]["status"] == "CONFLICT"
    assert comparisons["consignee_address"]["status"] == "MATCH"


@pytest.mark.parametrize("content", [
    "SELLER / EXPORTER\nExample Export Co., Ltd.\nBUYER / IMPORTER\nExample Import Inc.",
    "SHIPPER: Example Export Co., Ltd.\nEmail: seller@example.test\nTel: +86 574 1234567",
    "CONSIGNEE: Example Import Inc.\nContact: Jamie Taylor\nEmail: buyer@example.test\nTel: +1 206 1234567",
    "SELLER / EXPORTER\nEmail: seller@example.test\nTel: +86 574 1234567\nBUYER / IMPORTER\nEmail: buyer@example.test",
])
def test_company_labels_and_contacts_alone_do_not_become_address(content):
    assert_no_usable_address(extracted("COMMERCIAL INVOICE\n" + content))


@pytest.mark.parametrize("key,label", [
    ("shipper_address", "SHIPPER ADDRESS"),
    ("consignee_address", "CONSIGNEE ADDRESS"),
])
def test_empty_explicit_address_has_unrecognized_evidence(key, label):
    field = extracted(f"COMMERCIAL INVOICE\n{label}:\nEmail: contact@example.test\nTel: +1 206 1234567", page=2)[key]
    assert field["status"] == "UNRECOGNIZED", field
    assert field["normalized_value"] is None
    assert label in field["raw_text"]
    assert field["page"] == 2


@pytest.mark.parametrize("text", [
    # Flattened two-column party rows: ownership cannot be recovered from order.
    "SELLER / EXPORTER\nBUYER / IMPORTER\nExample Export Co., Ltd.\nExample Import Inc.\n"
    "24 Harbor Road, Suite 17\n742 Garden Street, Suite 36\n"
    "Ningbo, Zhejiang 315000, China\nSeattle, WA 98101, United States",
    # Column separation exists, but no source geometry proves cell ownership.
    "SELLER / EXPORTER          BUYER / IMPORTER\n"
    "Example Export Co., Ltd.   Example Import Inc.\n"
    "24 Harbor Road            742 Garden Street\n"
    "Ningbo 315000, China       Seattle WA 98101, United States",
])
def test_ambiguous_two_column_parties_never_cross_assign_address(text):
    fields = extracted("COMMERCIAL INVOICE\n" + text)
    for key in ADDRESS_KEYS:
        field = fields[key]
        assert field["status"] == "UNRECOGNIZED", field
        assert field["normalized_value"] is None


def test_address_not_truncated_to_old_eighty_character_text_limit():
    address = (
        "24 Harbor Road, Suite 17, Building North, Synthetic Logistics Demonstration Campus\n"
        "Industrial Development District, Ningbo, Zhejiang 315000, China"
    )
    assert len(address) > 100
    field = extracted(block_document(seller_address=address))["shipper_address"]
    assert field["raw_value"] == address
    assert "315000" in field["normalized_value"]
    assert "China" in field["raw_text"]


def test_address_conflict_after_eighty_characters_is_not_hidden():
    address = (
        "24 Harbor Road, Suite 17, Building North, Synthetic Logistics Demonstration Campus\n"
        "Industrial Development District, Ningbo, Zhejiang 315000, China"
    )
    changed = address.replace("315000", "315001")
    assert address[:80] == changed[:80]
    comparison = compare_texts(block_document(seller_address=address),
                               block_document(seller_address=changed))["shipper_address"]
    assert comparison["status"] == "CONFLICT", comparison


def test_duplicate_role_addresses_do_not_silently_take_first():
    text = (
        f"COMMERCIAL INVOICE\nCONSIGNEE ADDRESS: {BUYER_ADDRESS}\n"
        "Email: first@example.test\n"
        "CONSIGNEE ADDRESS: 999 Market Street, Suite 77\nSeattle, WA 98101, United States\n"
        "Email: second@example.test\n"
    )
    field = extracted(text)["consignee_address"]
    assert field["status"] == "UNRECOGNIZED", field
    assert field["normalized_value"] is None
    assert "742 Garden Street" in field["raw_text"]
    assert "999 Market Street" in field["raw_text"]


def test_overlong_address_is_rejected_instead_of_truncated():
    address = "24 Harbor Road, " + "Synthetic Industrial Unit " * 100
    assert len(address) > 2000
    field = extracted(f"COMMERCIAL INVOICE\nSHIPPER ADDRESS: {address}\nEmail: seller@example.test")["shipper_address"]
    assert field["status"] == "UNRECOGNIZED", field
    assert field["normalized_value"] is None
    assert field["raw_value"] is None


@pytest.mark.parametrize("placeholder", [SHIPPER, "N/A", "UNKNOWN", "*****", "ADDRESS", "NOT PROVIDED", "SKU"])
def test_explicit_address_company_or_placeholder_is_not_value(placeholder):
    field = extracted(f"COMMERCIAL INVOICE\nSHIPPER ADDRESS: {placeholder}\nEmail: seller@example.test")["shipper_address"]
    assert field["status"] == "UNRECOGNIZED", field
    assert field["normalized_value"] is None


def test_inline_contact_does_not_become_part_of_address():
    field = extracted("COMMERCIAL INVOICE\nSHIPPER ADDRESS: 24 Harbor Road, Tel: +86 574 1234567")["shipper_address"]
    assert field["status"] == "UNRECOGNIZED", field
    assert field["normalized_value"] is None


def test_house_number_prefix_is_not_confused_with_table_header():
    address = "No. 123 Garden Street, Suite 36\nSeattle, WA 98101, United States"
    field = extracted(block_document(buyer_address=address))["consignee_address"]
    assert field["status"] == "EXTRACTED", field
    assert field["raw_value"] == address


@pytest.mark.parametrize("label", ["ADDRESS", "NAME", "SKU", "ZIP CODE"])
def test_next_line_placeholder_label_is_not_address(label):
    field = extracted(f"COMMERCIAL INVOICE\nCONSIGNEE ADDRESS:\n{label}\nQTY: 500 PCS")["consignee_address"]
    assert field["status"] == "UNRECOGNIZED", field
    assert field["normalized_value"] is None


def test_city_beginning_with_tel_keeps_postcode_for_comparison():
    address = "10 Test Street\nTel Aviv 61000, Israel"
    changed = address.replace("61000", "62000")
    field = extracted(block_document(buyer_address=address))["consignee_address"]
    assert field["raw_value"] == address, field
    assert "61000" in field["normalized_value"]
    comparison = compare_texts(block_document(buyer_address=address),
                               block_document(buyer_address=changed))["consignee_address"]
    assert comparison["status"] == "CONFLICT", comparison


def test_second_address_line_beginning_with_origin_is_not_business_label():
    address = "10 Test Street\nOrigin Road 101\nLondon EC1A 1BB, United Kingdom"
    changed = address.replace("101", "202")
    field = extracted(block_document(buyer_address=address))["consignee_address"]
    assert field["raw_value"] == address, field
    comparison = compare_texts(block_document(buyer_address=address),
                               block_document(buyer_address=changed))["consignee_address"]
    assert comparison["status"] == "CONFLICT", comparison


@pytest.mark.parametrize("business_line", ["NET WEIGHT: 50 KG", "GROSS WEIGHT: 55 KG", "TOTAL AMOUNT: USD 1000"])
def test_compound_business_label_is_not_swallowed_into_address(business_line):
    field = extracted(f"COMMERCIAL INVOICE\nCONSIGNEE ADDRESS:\n10 Test Street\n{business_line}\nQTY: 500 PCS")["consignee_address"]
    assert field["status"] == "EXTRACTED", field
    assert field["raw_value"] == "10 Test Street"
    assert business_line not in field["raw_text"]


def test_company_name_containing_street_and_number_is_not_address():
    fields = extracted("COMMERCIAL INVOICE\nCONSIGNEE:\n7 Road Export Co.\nQTY: 500 PCS")
    field = fields.get("consignee_address")
    assert field is None or field["status"] not in {"EXTRACTED", "LOW_CONFIDENCE"}, field
    if field is not None:
        assert field["normalized_value"] is None


def test_absent_address_is_optional_and_single_source_is_not_compared():
    missing = "COMMERCIAL INVOICE\nSHIPPER: Example Export Co., Ltd.\nCONSIGNEE: Example Import Inc.\n"
    fields = extracted(missing)
    assert all(key not in fields or fields[key]["status"] == "NOT_IN_DOC" for key in ADDRESS_KEYS)
    comparisons = compare_texts(block_document(), missing)
    assert all(key not in comparisons for key in ADDRESS_KEYS), comparisons


def test_found_address_with_unreadable_peer_cannot_match():
    peer = "COMMERCIAL INVOICE\nCONSIGNEE ADDRESS:\nEmail: contact@example.test\n"
    comparison = compare_texts(block_document(), peer)["consignee_address"]
    assert comparison["status"] == "MISSING_IN_SOME", comparison
    assert comparison["note"]
    assert {v["field_status"] for v in comparison["values"]} == {"EXTRACTED", "UNRECOGNIZED"}


def test_address_page_evidence_is_unique_or_unknown():
    first = "COMMERCIAL INVOICE\nDocument No.: CI-PAGE-1\n"
    second = block_document()
    fields = list(extracted(first + second, page=None).values())
    tables = [TableResult([], text, set(), False, False) for text in (first, second)]
    _locate_document_pages(fields, tables, "COMMERCIAL_INVOICE")
    for field in fields:
        if field["field_key"] in ADDRESS_KEYS:
            assert field["page"] == 2, field
    repeated = [TableResult([], second, set(), False, False), TableResult([], second, set(), False, False)]
    _locate_document_pages(fields, repeated, "COMMERCIAL_INVOICE")
    for field in fields:
        if field["field_key"] in ADDRESS_KEYS:
            assert field["page"] is None, field


def original_dataset():
    value = os.environ.get("HACKATHON_ADDRESS_DATASET")
    if not value:
        pytest.skip("Set HACKATHON_ADDRESS_DATASET to run the original synthetic PDF cases")
    base = Path(value)
    for candidate in (base, base / "backend" / "samples", base / "trade_documents_hackathon_v2" / "backend" / "samples"):
        if (candidate / "SHP-00090" / "commercial_invoice.pdf").is_file():
            return candidate
    pytest.fail("HACKATHON_ADDRESS_DATASET does not contain the requested original PDF cases")


@pytest.mark.parametrize("shipment,original_street", [
    ("SHP-00090", "742 Garden Street, Suite 36"),
    ("SHP-00093", "425 Warehouse Street, Suite 4"),
    ("SHP-00100", "119 Union Street, Suite 30"),
])
def test_original_pdf_address_conflicts_are_detected(shipment, original_street):
    base = original_dataset() / shipment
    docs, extractions, fields_by_name = [], [], {}
    for filename in ("commercial_invoice.pdf", "packing_list.pdf", "proforma_invoice.pdf"):
        # Text-layer originals must succeed without any OCR/model fallback.
        with patch.object(reader, "PADDLE_OCR_ENABLED", False), patch.object(reader, "llm_enabled", return_value=False):
            result = reader.read_document(filename, (base / filename).read_bytes())
        assert result.ok, (shipment, filename, result.error_message)
        assert result.parse_method.value == "TEXT_LAYER"
        doc_type = classify.classify(result.text, filename)
        table = parse_line_items(result.text, page=1)
        fields = extract_fields(table.doc_text, doc_type, page=1, row_keys=table.header_keys or None)
        docs.append(document(filename, doc_type))
        extractions.append({"file_id": filename, "doc_type": doc_type, "parse_method": "TEXT_LAYER", "fields": fields})
        fields_by_name[filename] = {f["field_key"]: f for f in fields}
        for key in ADDRESS_KEYS:
            field = fields_by_name[filename][key]
            assert field["status"] == "EXTRACTED", (shipment, filename, field)
            assert field["page"] == 1
            assert all(line in result.text for line in field["raw_value"].splitlines())
            assert all(line in field["raw_text"] for line in field["raw_value"].splitlines())
    comparisons = {c["field_key"]: c for c in build_comparisons(docs, extractions, lambda *_: False)}
    conflict = comparisons["consignee_address"]
    assert conflict["status"] == "CONFLICT", (shipment, conflict)
    assert len(conflict["values"]) == 3
    assert "999 Different Market Street, Suite 77" in fields_by_name["commercial_invoice.pdf"]["consignee_address"]["raw_value"]
    for filename in ("packing_list.pdf", "proforma_invoice.pdf"):
        assert original_street in fields_by_name[filename]["consignee_address"]["raw_value"]
    assert comparisons["shipper_address"]["status"] == "MATCH"
    assert comparisons["shipper"]["status"] == "MATCH"
    assert comparisons["consignee"]["status"] == "MATCH"
