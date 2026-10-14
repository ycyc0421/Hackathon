"""Keep adjacent invoice totals separate without accepting contaminated units."""

import pytest

from app.pipeline.extract import extract_fields


def field(text, key, doc_type="COMMERCIAL_INVOICE"):
    return next(value for value in extract_fields(text, doc_type, page=2)
                if value["field_key"] == key)


@pytest.mark.parametrize("separator", [" ", "\t", "  ", " | "])
def test_invoice_totals_preserve_values_units_and_original_evidence(separator):
    text = separator.join([
        "合计/TOTAL: 9600 PCS", "120 CARTONS", "G.W. 2,800.00 KGS",
        "AMOUNT USD 13,500.00",
    ])
    expected = {
        "quantity": (9600, "PCS"),
        "packages": (120, "CARTON"),
        "gross_weight": (2800, "KGS"),
        "total_amount": (13500, "USD"),
    }
    for key, (value, unit) in expected.items():
        actual = field(text, key)
        assert actual["status"] == "EXTRACTED"
        assert actual["normalized_value"] == value
        assert actual["unit"] == unit
        assert actual["raw_text"] == text
        assert actual["page"] == 2
        assert actual["confidence"] is None
    assert field(text, "packages")["raw_value"] == "120 CARTONS"
    assert field(text, "gross_weight")["raw_value"] == "2,800.00 KGS"


@pytest.mark.parametrize("following", [
    "G.W. 45 KGS", "GROSS WEIGHT: 45 KGS", "N.W. 40 KGS",
    "NET WEIGHT 40 KGS", "QTY 90 PCS", "VOLUME 1.2 CBM",
    "AMOUNT USD 80.00", "毛重：45 KGS", "净重 40 KGS",
])
def test_one_space_before_an_explicit_measure_label_ends_package_value(following):
    text = "PACKAGES: 9 CTNS " + following
    actual = field(text, "packages")
    assert actual["status"] == "EXTRACTED"
    assert actual["normalized_value"] == 9
    assert actual["unit"] == "CARTON"
    assert actual["raw_value"] == "9 CTNS"
    assert actual["raw_text"] == text


@pytest.mark.parametrize("text,key", [
    ("PACKAGES: 9 PALLETS G.W. 45 KGS", "packages"),
    ("G.W. 45 OUNCES AMOUNT USD 80.00", "gross_weight"),
    ("PACKAGES: 9 CTNS OTHER 20", "packages"),
    ("G.W. 45 KGS AMOUNT UNKNOWN", "gross_weight"),
    ("PACKAGES: 9 CTNS GROSS MATERIAL", "packages"),
    ("PACKAGES: 9 CTNS 10 CTNS", "packages"),
])
def test_unknown_units_and_unrecognized_extra_content_still_fail(text, key):
    actual = field(text, key)
    assert actual["status"] == "NORMALIZE_FAILED"
    assert actual["normalized_value"] is None
    assert actual["unit"] is None
    assert actual["raw_text"] == text


@pytest.mark.parametrize("text,key,value,unit", [
    ("TOTAL CARTONS: 9   CTNS", "packages", 9, "CARTON"),
    ("PACKAGES: 9 PKGS G.W. 45 KGS", "packages", 9, None),
    ("G.W. 45   KGS", "gross_weight", 45, "KGS"),
    ("G.W. 100 LBS AMOUNT USD 80.00", "gross_weight", 45.359237, "KGS"),
])
def test_measure_spacing_generic_packaging_and_pounds_conversion_remain_valid(text, key, value, unit):
    actual = field(text, key)
    assert actual["status"] == "EXTRACTED"
    assert actual["normalized_value"] == value
    assert actual["unit"] == unit


def test_packing_list_quantity_and_weight_are_not_fabricated_as_money():
    text = "TOTAL: 90 PCS 9 CTNS G.W. 45 KGS"
    for key, value in [("quantity", 90), ("packages", 9), ("gross_weight", 45)]:
        actual = field(text, key, "PACKING_LIST")
        assert actual["status"] == "EXTRACTED"
        assert actual["normalized_value"] == value
    amount = field(text, "total_amount", "PACKING_LIST")
    assert amount["status"] == "NOT_IN_DOC"
    assert amount["normalized_value"] is None
