"""Bounded INVOIC D.96A regressions using synthetic bytes, without OCR/LLM.

The original EDI fixtures and their independent creation expectations stay
unchanged. These checks establish the declared subset, not EDIFACT certification.
"""

import json
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Extraction
from app.pipeline.edifact import EdifactUnsupported, parse_edifact
from app.pipeline import reader
from test_api_samples import validate_response


ROOT = Path(__file__).resolve().parents[2]
EDI = ROOT / "backend/samples/edi"
CREATION_EXPECTATIONS = json.loads((EDI / "expected.json").read_text(encoding="utf-8"))
SUPPORTED = [
    (EDI / case["case_id"] / document["file_name"], document)
    for case in CREATION_EXPECTATIONS["cases"]
    if case["case_id"] not in {"10_multi_message", "11_bad_unt_count", "12_truncated"}
    for document in case["documents"].values()
    if document["message_type"] == "INVOIC"
]


def field(fields, key):
    return next(value for value in fields if value["field_key"] == key
                and value.get("item_id") is None)


def message(body, *, reference="42", interchange="TEST42"):
    """Construct the envelope independently of the parser under test."""
    segments = [f"UNH+{reference}+INVOIC:D:96A:UN", *body]
    return (f"UNB+UNOC:3+SYNTHETIC-SENDER+SYNTHETIC-RECEIVER+261014:1200+{interchange}'"
            + "'".join(segments)
            + f"'UNT+{len(segments) + 1}+{reference}'UNZ+1+{interchange}'").encode("utf-8")


def one_line_body():
    return ["BGM+380+SYNTHETIC-CI-42+9", "CUX+2:USD:4", "LIN+1++SKU-42:SA",
            "IMD+F++:::SYNTHETIC ITEM", "QTY+47:7:PCE", "MOA+203:21.00",
            "PRI+AAA:3.00:::1:PCE", "UNS+S", "MOA+77:21.00"]


def parse_or_explicit_rejection(data):
    try:
        return parse_edifact(data)
    except ValueError:
        return None


@pytest.mark.parametrize("path,expected", SUPPORTED,
                         ids=[str(path.relative_to(EDI)) for path, _ in SUPPORTED])
def test_original_complete_invoices_preserve_fields_and_scope(path, expected):
    original = path.read_bytes()
    result = parse_edifact(original)
    Extraction.model_validate({"file_id": "f1", "parse_method": "EDI_PARSE", **result})
    assert result["doc_type"] == "COMMERCIAL_INVOICE"
    assert field(result["fields"], "document_no")["normalized_value"] == expected["document_no"]
    assert field(result["fields"], "invoice_no")["normalized_value"] == expected["invoice_no"]
    assert field(result["fields"], "shipment_date")["normalized_value"] == expected["shipment_date"]
    assert field(result["fields"], "destination_country")["normalized_value"] == expected["destination_country"]
    assert field(result["fields"], "shipper")["raw_value"] == "SYNTHETIC SUPPLIER LTD"
    assert field(result["fields"], "consignee")["raw_value"] == "SYNTHETIC BUYER LTD"
    units = {"packages": "CARTON", "gross_weight": "KGS", "net_weight": "KGS", "volume": "CBM"}
    for key, unit in units.items():
        actual = field(result["fields"], key)
        assert actual["normalized_value"] == pytest.approx(float(expected["header"][key]))
        assert actual["unit"] == unit
    total = field(result["fields"], "total_amount")
    assert total["normalized_value"] == pytest.approx(float(expected["header"]["total_amount"]))
    assert total["unit"] == expected["currency"]
    assert field(result["fields"], "currency")["normalized_value"] == expected["currency"]
    # Header quantities are not present in these messages: do not invent a total.
    assert field(result["fields"], "quantity")["normalized_value"] is None
    assert len(result["line_items"]) == len(expected["items"])
    for row, gold in zip(result["line_items"], expected["items"]):
        assert row["item_no"] == gold["line_no"]
        assert field(row["fields"], "item_code")["normalized_value"] == gold["item_code"]
        assert field(row["fields"], "description")["raw_value"] == gold["description"]
        assert field(row["fields"], "hs_code")["normalized_value"] == gold["hs_code"]
        for key in ("quantity", "packages", "net_weight", "gross_weight", "unit_price", "amount"):
            actual = field(row["fields"], key)
            assert actual["normalized_value"] == pytest.approx(float(gold[key]))
            assert actual["unit"] == ("PCS" if key == "quantity" else
                                      "CARTON" if key == "packages" else
                                      "KGS" if key.endswith("weight") else expected["currency"])
    for actual in [*result["fields"], *(f for row in result["line_items"] for f in row["fields"])]:
        assert actual["page"] is None and actual["bbox"] is None
        assert actual["confidence"] is None
        if actual["status"] == "EXTRACTED":
            assert actual["raw_text"]
            assert actual["raw_text"] in original.decode("utf-8")


def test_release_characters_decode_values_but_keep_original_evidence():
    original = (EDI / "08_release_characters/01_invoic.edi").read_bytes()
    result = parse_edifact(original)
    actual = field(result["line_items"][0]["fields"], "description")
    assert actual["raw_value"] == "GIFT SET + CUP: 350ML? WHITE'S"
    assert "IMD+F++:::GIFT SET ?+ CUP?: 350ML?? WHITE?'S" in actual["raw_text"]


def test_custom_una_and_decimal_comma_compact_streams():
    canonical = message(one_line_body())
    custom = b"UNA|;.! ~" + canonical.decode().translate(str.maketrans({":": "|", "+": ";", "'": "~"})).encode()
    result = parse_edifact(custom)
    assert field(result["line_items"][0]["fields"], "quantity")["normalized_value"] == 7
    assert field(result["fields"], "total_amount")["normalized_value"] == 21
    comma = parse_edifact((EDI / "09_decimal_comma_compact/01_invoic.edi").read_bytes())
    assert field(comma["fields"], "gross_weight")["normalized_value"] == 1080.5
    assert field(comma["fields"], "net_weight")["normalized_value"] == 900.25
    assert field(comma["line_items"][0]["fields"], "unit_price")["normalized_value"] == 2.05


def test_four_rows_keep_message_order_and_sku_identity():
    body = ["BGM+380+SYNTHETIC-CI-FOUR+9", "CUX+2:EUR:4"]
    skus = ["SKU-D", "SKU-A", "SKU-C", "SKU-B"]
    quantities = [7, 11, 13, 17]
    for number, (sku, quantity) in enumerate(zip(skus, quantities), 1):
        body += [f"LIN+{number}++{sku}:SA", f"IMD+F++:::SYNTHETIC {sku}",
                 f"QTY+47:{quantity}:PCE", f"MOA+203:{quantity * 3}.00", "PRI+AAA:3.00:::1:PCE"]
    body += ["UNS+S", "MOA+77:144.00"]
    result = parse_edifact(message(body))
    assert [row["item_no"] for row in result["line_items"]] == [1, 2, 3, 4]
    assert [field(row["fields"], "item_code")["normalized_value"] for row in result["line_items"]] == skus
    assert [field(row["fields"], "quantity")["normalized_value"] for row in result["line_items"]] == quantities
    assert field(result["fields"], "total_amount")["normalized_value"] == 144


def test_strict_utf8_description_is_supported_without_lossy_decoding():
    original = message([s.replace("SYNTHETIC ITEM", "合成陶瓷杯") for s in one_line_body()])
    result = parse_edifact(original)
    actual = field(result["line_items"][0]["fields"], "description")
    assert actual["raw_value"] == "合成陶瓷杯"
    assert actual["raw_text"] in original.decode("utf-8")


@pytest.mark.parametrize("mutation", [
    lambda x: x.replace(b"SYNTHETIC ITEM", b"SYNTHETIC?\x00ITEM"),
    lambda x: x.replace(b"SYNTHETIC ITEM", b"SYNTHETIC?XITEM"),
    lambda x: "UNA:+.§ '".encode("utf-8") + x,
    lambda x: x.replace(b"UNB+UNOC:3", b"UNB+WRONG:3"),
    lambda x: x.replace(b"+SYNTHETIC-SENDER+", b"++"),
    lambda x: x.replace(b"+SYNTHETIC-RECEIVER+", b"++"),
    lambda x: x.replace(b"PRI+AAA:3.00:::1:PCE", b"PRI+AAA:3.00:::1:PCE+1"),
    lambda x: x.replace(b"QTY+47:7:PCE", b"QTY+47:7:PCE+EXTRA"),
], ids=["escaped-control-byte", "invalid-release-sequence", "non-ascii-service-character",
        "unknown-syntax-id", "empty-sender", "empty-receiver", "extra-price-element", "extra-qty-element"])
def test_service_and_segment_structure_does_not_silently_discard_data(mutation):
    with pytest.raises(ValueError):
        parse_edifact(mutation(message(one_line_body())))


@pytest.mark.parametrize("body", [
    [s.replace("BGM+380+SYNTHETIC-CI-42+9", "BGM+380+SYNTHETIC-CI-42+9+EXTRA") for s in one_line_body()],
    [s.replace("LIN+1++SKU-42:SA", "LIN+1++SKU-42:SA+EXTRA") for s in one_line_body()],
    one_line_body()[:2] + ["PAC+1++CT+EXTRA"] + one_line_body()[2:],
    one_line_body()[:2] + ["MEA+AAE+AAD+KGM:1+EXTRA"] + one_line_body()[2:],
    [s.replace("MOA+203:21.00", "MOA+203:21.00+EXTRA") for s in one_line_body()],
    [s.replace("PRI+AAA:3.00:::1:PCE", "PRI+AAA:3.00:::1:PCE+EXTRA") for s in one_line_body()],
], ids=["bgm", "lin", "pac", "mea", "moa", "pri"])
def test_extra_business_elements_are_not_silently_ignored(body):
    with pytest.raises(ValueError):
        parse_edifact(message(body))


@pytest.mark.parametrize("data", [
    message([s.replace("LIN+1++SKU-42:SA", "LIN+1:EXTRA++SKU-42:SA") for s in one_line_body()]),
    message(one_line_body()[:2] + ["NAD+CN:EXTRA+++SYNTHETIC BUYER LTD+1 TEST ROAD+TESTCITY++00000+DE"]
            + one_line_body()[2:]),
    message(one_line_body()[:3] + ["PIA+1:EXTRA+691110:HS"] + one_line_body()[3:]),
    message([s.replace("IMD+F++", "IMD+F:EXTRA++") for s in one_line_body()]),
    message(one_line_body()[:2] + ["DTM+11:20261014:102+EXTRA"] + one_line_body()[2:]),
    message(one_line_body()[:8] + ["CNT+2:1+EXTRA"] + one_line_body()[8:]),
    b"\x1c" + message(one_line_body()),
    message([s.replace("SYNTHETIC ITEM", "SYNTHETIC\x7fITEM") for s in one_line_body()]),
], ids=["lin-scalar-components", "nad-scalar-components", "pia-scalar-components",
        "imd-scalar-components", "dtm-extra-element", "cnt-extra-element",
        "leading-control-not-whitespace", "del-in-description"])
def test_scalar_metadata_and_control_bytes_are_not_dropped(data):
    with pytest.raises(ValueError):
        parse_edifact(data)


@pytest.mark.parametrize("segment,key,expected,row", [
    ("NAD+CN+++SYNTHETIC BUYER LTD:::::1+1 TEST ROAD+TESTCITY++00000+DE",
     "consignee", "SYNTHETIC BUYER LTD", False),
    ("IMD+F++:::SYNTHETIC ITEM::EN", "description", "SYNTHETIC ITEM", True),
], ids=["party-name-format-code", "description-language-code"])
def test_metadata_codes_never_become_party_or_product_text(segment, key, expected, row):
    body = one_line_body()
    if row:
        body[3] = segment
    else:
        body.insert(1, segment)
    result = parse_or_explicit_rejection(message(body))
    if result is not None:
        actual = field(result["line_items"][0]["fields"] if row else result["fields"], key)
        assert actual["raw_value"] == expected


def test_buyer_is_not_invented_as_consignee_or_destination():
    body = one_line_body()
    body.insert(1, "NAD+BY+++SYNTHETIC BUYER LTD+1 TEST ROAD+TESTCITY++00000+US")
    result = parse_or_explicit_rejection(message(body))
    if result is not None:
        relevant = [f for f in result["fields"] if f["field_key"] in {"consignee", "destination_country"}]
        assert all(f["normalized_value"] is None for f in relevant)


@pytest.mark.parametrize("mutation", [
    lambda x: x.replace(b"UNT+11+42", b"UNT+12+42"),
    lambda x: x.replace(b"UNT+11+42", b"UNT+11+43"),
    lambda x: x.replace(b"UNZ+1+TEST42", b"UNZ+2+TEST42"),
    lambda x: x.replace(b"UNZ+1+TEST42", b"UNZ+1+WRONG"),
    lambda x: x[:x.index(b"UNT+")],
    lambda x: x[:x.index(b"UNZ+")],
    lambda x: x[:-1],
    lambda x: x.replace(b"SYNTHETIC ITEM", b"BAD\xffBYTE"),
    lambda x: x + b"TRAILING GARBAGE",
], ids=["unt-count", "unt-reference", "unz-count", "unz-reference", "missing-trailers",
        "missing-unz", "unterminated", "invalid-utf8", "trailing-garbage"])
def test_malformed_envelopes_never_return_extractions(mutation):
    original = message(one_line_body())
    damaged = mutation(original)
    assert damaged != original
    with pytest.raises(ValueError):
        parse_edifact(damaged)


@pytest.mark.parametrize("path", sorted(EDI.glob("*/**/*.edi")), ids=lambda p: str(p.relative_to(EDI)))
def test_all_original_files_have_explicit_support_boundary(path):
    data = path.read_bytes()
    if path.parent.name in {"11_bad_unt_count", "12_truncated"}:
        with pytest.raises(ValueError) as error:
            parse_edifact(data)
        assert not isinstance(error.value, EdifactUnsupported), "Invalid syntax takes precedence over message support"
    elif "DESADV" in data.decode() or path.parent.name == "10_multi_message":
        with pytest.raises(EdifactUnsupported):
            parse_edifact(data)
    else:
        assert parse_edifact(data)["doc_type"] == "COMMERCIAL_INVOICE"


@pytest.mark.parametrize("unsupported", [
    b"ISA*00*          *00*          *ZZ*SYNTHETIC~GS*IN*SYNTHETIC~",
    message(one_line_body()).replace(b"INVOIC:D:96A:UN", b"INVOIC:D:01B:UN"),
    message(one_line_body()).replace(b"INVOIC:D:96A:UN", b"DESADV:D:96A:UN"),
    message(one_line_body()).replace(b"PRI+AAA:3.00:::1:PCE", b"PRI+AAA:3.00:::100:PCE"),
], ids=["x12", "other-directory", "desadv", "price-per-hundred"])
def test_outside_subset_is_explicitly_unsupported(unsupported):
    with pytest.raises(EdifactUnsupported):
        parse_edifact(unsupported)


@pytest.mark.parametrize("body,key,row", [
    (one_line_body()[:2] + ["CUX+2:EUR:4"] + one_line_body()[2:], "currency", False),
    (one_line_body()[:5] + ["QTY+47:9:PCE"] + one_line_body()[5:], "quantity", True),
    ([segment.replace("QTY+47:7:PCE", "QTY+99:999:PCE")
      for segment in one_line_body()], "quantity", True),
    ([segment.replace("MOA+203:21.00", "MOA+999:999.00")
      for segment in one_line_body()], "amount", True),
    ([segment.replace("QTY+47:7:PCE", "QTY+47:1,000:PCE")
      for segment in one_line_body()], "quantity", True),
], ids=["conflicting-currencies", "conflicting-quantities", "unknown-qty-qualifier",
        "unknown-money-qualifier", "grouped-number"])
def test_ambiguous_or_unknown_values_are_not_guessed(body, key, row):
    # Rejection is allowed; a usable guessed value is not.
    result = parse_or_explicit_rejection(message(body))
    if result is not None:
        actual = field(result["line_items"][0]["fields"] if row else result["fields"], key)
        assert actual["normalized_value"] is None
        assert actual["status"] not in {"EXTRACTED", "LOW_CONFIDENCE"}


def test_size_and_line_limits_are_enforced():
    with pytest.raises(ValueError):
        parse_edifact(b" " * (1024 * 1024 + 1))
    body = ["BGM+380+SYNTHETIC-TOO-MANY+9"]
    for number in range(1, 202):
        body += [f"LIN+{number}++SKU-{number}:SA", "IMD+F++:::SYNTHETIC ITEM", "QTY+47:1:PCE"]
    with pytest.raises(ValueError):
        parse_edifact(message(body))


def test_edi_reader_uses_structured_path_without_ocr(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Standard EDI must not call PDF/image/OCR extraction")
    monkeypatch.setattr(reader, "_read_pdf", forbidden)
    monkeypatch.setattr(reader, "_read_image", forbidden)
    assert reader.guess_file_type("INVOICE.EDI").value == "EDI"
    assert reader.guess_file_type("invoice.txt").value == "OTHER"
    result = reader.read_document("INVOICE.EDI", message(one_line_body()))
    assert result.ok and result.parse_method.value == "EDI_PARSE"
    assert result.page_count is None
    assert result.structured["doc_type"] == "COMMERCIAL_INVOICE"


def upload(client, files):
    response = client.post("/api/v1/checks", data={"destination_country": "DE"},
                           files=[("files", (name, data, mime)) for name, data, mime in files])
    assert response.status_code == 200, response.text
    task_id = response.json()["task_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/checks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] in {"COMPLETED", "PARTIAL", "FAILED"}:
            return task
        time.sleep(.02)
    pytest.fail(f"Isolated EDI task did not complete: {task_id}")


@pytest.mark.integration
def test_http_edi_completion_contract_report_and_original_bytes(client, validate_response):
    original = (EDI / "07_multiitem_reordered/01_invoic.edi").read_bytes()
    task = upload(client, [("INVOICE.EDI", original, "application/octet-stream")])
    validate_response(task)
    assert task["status"] == "COMPLETED"
    assert task["documents"][0]["file_type"] == "EDI"
    assert task["documents"][0]["process_status"] == "EXTRACTED"
    assert task["extractions"][0]["parse_method"] == "EDI_PARSE"
    assert {f.get("line_no") for f in task["extractions"][0]["fields"] if f.get("line_no")} == {1, 2, 3}
    assert not any(error["code"] in {"DOC_PARSE_FAILED", "UNSUPPORTED_FILE_TYPE"} for error in task["errors"])
    original_response = client.get(f"/api/v1/checks/{task['task_id']}/files/f1")
    assert original_response.status_code == 200
    assert original_response.content == original
    assert "attachment" in original_response.headers["content-disposition"]
    assert original_response.headers["x-content-type-options"] == "nosniff"
    report_response = client.get(f"/api/v1/checks/{task['task_id']}/report?format=json&view=content")
    assert report_response.status_code == 200, report_response.text
    validate_response(report_response.json(), "report", report=True)


@pytest.mark.integration
def test_http_mixed_pdf_invoice_and_unsupported_desadv_remains_partial(client, validate_response):
    invoice = (EDI / "01_consistent/01_invoic.edi").read_bytes()
    desadv = (EDI / "01_consistent/02_desadv.edi").read_bytes()
    pdf = next((ROOT / "backend/samples/01_us_consistent").glob("*.pdf"))
    task = upload(client, [("invoice.edi", invoice, "application/octet-stream"),
                           ("desadv.edi", desadv, "application/octet-stream"),
                           (pdf.name, pdf.read_bytes(), "application/pdf")])
    validate_response(task)
    assert task["status"] == "PARTIAL"
    assert [d["process_status"] for d in task["documents"]] == ["EXTRACTED", "UNSUPPORTED", "EXTRACTED"]
    assert {e["file_id"] for e in task["extractions"]} == {"f1", "f3"}
    assert any(error["code"] == "UNSUPPORTED_FILE_TYPE" and error["file_ids"] == ["f2"]
               for error in task["errors"])
    response = client.get(f"/api/v1/checks/{task['task_id']}/files/f2")
    assert response.status_code == 200 and response.content == desadv


@pytest.mark.integration
@pytest.mark.parametrize("path", ["11_bad_unt_count/01_invoic.edi", "12_truncated/01_desadv.edi"])
def test_http_invalid_edi_fails_instead_of_zero_conflict_success(client, validate_response, path):
    original = (EDI / path).read_bytes()
    task = upload(client, [("bad-count.edi", original, "application/octet-stream")])
    validate_response(task)
    assert task["status"] == "FAILED"
    assert task["documents"][0]["process_status"] == "FAILED"
    assert not task["extractions"]
    assert any(error["code"] == "DOC_PARSE_FAILED" for error in task["errors"])
    assert not any(value["status"] == "MATCH" for value in task["comparisons"])
    assert client.get(f"/api/v1/checks/{task['task_id']}/files/f1").content == original


@pytest.mark.integration
@pytest.mark.parametrize("case,key", [("04_amount_conflict", "total_amount"),
                                      ("05_currency_conflict", "currency")])
def test_http_supported_invoice_conflicts_are_detected(client, validate_response, case, key):
    files = sorted((EDI / case).glob("*invoic*.edi"))
    task = upload(client, [(p.name, p.read_bytes(), "application/octet-stream") for p in files])
    validate_response(task)
    assert task["status"] == "COMPLETED"
    assert any(value["field_key"] == key and value["status"] == "CONFLICT"
               for value in task["comparisons"])
    if key == "total_amount":
        assert any(value["field_key"] == "amount" and value["status"] == "CONFLICT"
                   for value in task["comparisons"])


@pytest.mark.integration
def test_http_missing_currency_and_hs_do_not_invent_defaults_or_money_match(client, validate_response):
    original = (EDI / "06_missing_hs_currency/01_invoic.edi").read_bytes()
    task = upload(client, [("missing.edi", original, "application/octet-stream"),
                           ("missing-copy.edi", original, "application/octet-stream")])
    validate_response(task)
    assert task["status"] == "COMPLETED"
    for extraction in task["extractions"]:
        assert field(extraction["fields"], "currency")["normalized_value"] is None
        assert field(extraction["fields"], "total_amount")["unit"] is None
        row_hs = [f for f in extraction["fields"] if f["field_key"] == "hs_code" and f.get("line_no")]
        assert row_hs and all(f["normalized_value"] is None for f in row_hs)
    money = [value for value in task["comparisons"] if value["field_key"] in {"total_amount", "amount", "unit_price"}]
    assert money and all(value["status"] == "NOT_CHECKED" for value in money)
    assert all(value.get("note") for value in money)


@pytest.mark.integration
def test_http_correction_retains_edi_original_and_source_evidence(client, validate_response):
    original = message(one_line_body())
    source = upload(client, [("synthetic.edi", original, "application/octet-stream")])
    source_id = source["task_id"]
    context = client.get(f"/api/v1/checks/{source_id}/corrections")
    assert context.status_code == 200
    request = {"request_id": "edi-regression-currency", "source_hash": context.json()["result_hash"],
               "reason": "Synthetic test correction", "changes": [
                   {"file_id": "f1", "field_key": "currency", "value": "EUR"}]}
    response = client.post(f"/api/v1/checks/{source_id}/corrections", json=request)
    assert response.status_code == 200, response.text
    corrected_id = response.json()["task_id"]
    assert corrected_id != source_id
    corrected = client.get(f"/api/v1/checks/{corrected_id}").json()
    validate_response(corrected)
    assert field(corrected["extractions"][0]["fields"], "currency")["normalized_value"] == "EUR"
    assert field(corrected["extractions"][0]["fields"], "total_amount")["unit"] == "EUR"
    assert field(corrected["extractions"][0]["fields"], "currency")["raw_value"] == "USD"
    assert field(client.get(f"/api/v1/checks/{source_id}").json()["extractions"][0]["fields"],
                 "currency")["normalized_value"] == "USD"
    assert client.get(f"/api/v1/checks/{corrected_id}/files/f1").content == original
    assert client.post(f"/api/v1/checks/{source_id}/corrections", json=request).json()["task_id"] == corrected_id
