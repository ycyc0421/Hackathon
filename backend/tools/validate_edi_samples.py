"""Independent bounded checker for the synthetic EDI fixture profile.

Checks envelope integrity, selected D.96A segment order, and fixture business
values. Does not implement the application's reader or full directory/MIG QA.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path


def split_released(text, separator, release):
    pieces, current, pos = [], [], 0
    while pos < len(text):
        char = text[pos]
        if char == release:
            if pos + 1 >= len(text):
                raise ValueError("DANGLING_RELEASE_CHARACTER")
            current.extend((char, text[pos + 1])); pos += 2
            continue
        if char == separator:
            pieces.append("".join(current)); current = []
        else:
            current.append(char)
        pos += 1
    pieces.append("".join(current))
    return pieces


def unescape(text, release):
    out, pos = [], 0
    while pos < len(text):
        if text[pos] == release:
            pos += 1
        out.append(text[pos]); pos += 1
    return "".join(out)


def decode(text):
    if not text.startswith("UNA") or len(text) < 9:
        raise ValueError("MISSING_UNA")
    component, element, decimal, release, _, terminator = text[3:9]
    segments = []
    for raw in split_released(text[9:], terminator, release):
        if not raw.strip():
            continue
        parts = split_released(raw.strip(), element, release)
        segments.append((parts[0], [[unescape(value, release) for value in split_released(part, component, release)]
                                   for part in parts[1:]]))
    return segments, decimal


def envelopes(segments):
    errors, messages, current = [], [], None
    if not segments or segments[0][0] != "UNB":
        return [], ["MISSING_UNB"]
    interchange_reference = segments[0][1][4][0]
    references = set()
    for tag, elements in segments[1:]:
        if tag == "UNH":
            if current is not None:
                errors.append("MISSING_UNT")
            current = [(tag, elements)]
            reference = elements[0][0]
            if reference in references:
                errors.append("DUPLICATE_MESSAGE_REFERENCE")
            references.add(reference)
        elif tag == "UNT":
            if current is None:
                errors.append("UNEXPECTED_UNT"); continue
            current.append((tag, elements))
            if int(elements[0][0]) != len(current):
                errors.append("UNT_COUNT_MISMATCH")
            if elements[1][0] != current[0][1][0][0]:
                errors.append("UNT_REFERENCE_MISMATCH")
            messages.append(current); current = None
        elif tag == "UNZ":
            if elements[1][0] != interchange_reference:
                errors.append("UNZ_REFERENCE_MISMATCH")
            if int(elements[0][0]) != len(messages):
                errors.append("UNZ_COUNT_MISMATCH")
        elif current is not None:
            current.append((tag, elements))
        else:
            errors.append("SEGMENT_OUTSIDE_MESSAGE")
    if current is not None:
        errors.append("MISSING_UNT")
    if segments[-1][0] != "UNZ":
        errors.append("MISSING_UNZ")
    return messages, errors


def order_check(message):
    kind = message[0][1][1][0]
    if message[0][1][1] != [kind, "D", "96A", "UN"] or kind not in {"INVOIC", "DESADV"}:
        raise ValueError("UNSUPPORTED_FIXTURE_DIRECTORY")
    if message[1][0] != "BGM":
        raise ValueError("MISSING_BGM")
    header_order = ({"UNH": 0, "BGM": 1, "DTM": 2, "FTX": 3, "RFF": 4,
                     "NAD": 5, "CUX": 6, "PAC": 7, "MEA": 8} if kind == "INVOIC" else
                    {"UNH": 0, "BGM": 1, "DTM": 2, "MEA": 3, "RFF": 4, "NAD": 5})
    detail_order = {"LIN": 0, "PIA": 1, "IMD": 2, "MEA": 3, "QTY": 4, "MOA": 5, "PRI": 6, "PAC": 7}
    phase, last_rank, saw_date, saw_summary, summary_money = "header", -1, False, False, False
    for tag, elements in message:
        if tag == "UNT":
            break
        if tag == "DTM":
            saw_date = True
        if tag == "UNS":
            if kind != "INVOIC" or elements != [["S"]]:
                raise ValueError("BAD_SUMMARY_MARKER")
            phase, last_rank, saw_summary = "summary", -1, True
        elif tag == "CNT" and kind == "DESADV":
            phase, last_rank = "summary", -1
        elif tag == "CPS":
            if kind != "DESADV":
                raise ValueError("CPS_IN_INVOICE")
            phase, last_rank = "packing", -1
        elif tag == "LIN":
            phase, last_rank = "detail", -1
        if phase == "header":
            rank = header_order[tag]
        elif phase == "packing":
            rank = {"CPS": 0, "PAC": 1}[tag]
        elif phase == "detail":
            rank = detail_order[tag]
        else:
            rank = {"UNS": 0, "CNT": 1, "MOA": 2}[tag]
            if tag == "MOA":
                summary_money = True
        if rank < last_rank:
            raise ValueError("SEGMENT_ORDER_ERROR")
        last_rank = rank
    if kind == "INVOIC" and not (saw_date and saw_summary and summary_money):
        raise ValueError("MISSING_INVOICE_MANDATORY_SEGMENT")


def business_read(message, decimal):
    def numeric(raw):
        return Decimal(raw.replace(decimal, "."))
    kind, reference = message[0][1][1][0], message[0][1][0][0]
    result = dict(message_type=kind, message_reference=reference, currency=None, items=[], header={})
    current, package, summary = None, None, False
    package_sum = 0
    for tag, e in message:
        if tag == "BGM":
            result["document_no"] = e[1][0]
        elif tag == "DTM":
            raw = e[0][1]
            if e[0][2] != "102" or len(raw) != 8:
                raise ValueError("BAD_DATE_FORMAT")
            key = {"137": "document_date", "11": "shipment_date"}.get(e[0][0])
            if key:
                result[key] = raw[:4] + "-" + raw[4:6] + "-" + raw[6:]
        elif tag == "RFF":
            key = {"ON": "order_no", "IV": "invoice_no"}.get(e[0][0])
            if key:
                result[key] = e[0][1]
        elif tag == "NAD" and e[0][0] == "CN":
            result["destination_country"] = e[8][0]
        elif tag == "CUX":
            result["currency"] = e[0][1]
        elif tag == "CPS":
            current, package = None, None
        elif tag == "PAC":
            if e[2] != ["CT"]:
                raise ValueError("UNEXPECTED_PACKAGE_UNIT")
            value = int(e[0][0])
            if kind == "DESADV":
                package, package_sum = value, package_sum + value
            elif current is None:
                result["header"]["packages"] = value
            else:
                current["packages"] = value
        elif tag == "LIN":
            current = dict(item_code=e[2][0], line_no=int(e[0][0]), hs_code=None,
                           unit_price=None, amount=None, quantity_unit="PCE", weight_unit="KGM", package_unit="CT")
            if kind == "DESADV":
                current["packages"] = package
            result["items"].append(current)
        elif tag == "PIA":
            if e[1][1] == "HS":
                current["hs_code"] = e[1][0]
        elif tag == "IMD":
            current["description"] = e[2][3]
        elif tag == "MEA":
            key = {"AAD": "gross_weight", "AAC": "net_weight", "AAW": "volume",
                   "AAE": "gross_weight", "AAL": "net_weight"}[e[1][0]]
            value = numeric(e[2][1])
            target = current if current is not None else result["header"]
            target[key] = value
        elif tag == "QTY":
            if e[0][0] != ("47" if kind == "INVOIC" else "12") or e[0][2] != "PCE":
                raise ValueError("BAD_QUANTITY_QUALIFIER_OR_UNIT")
            current["quantity"] = int(numeric(e[0][1]))
        elif tag == "PRI":
            if e[0][4:] != ["1", "PCE"]:
                raise ValueError("BAD_PRICE_BASIS")
            current["unit_price"] = numeric(e[0][1])
        elif tag == "UNS":
            summary = True
        elif tag == "MOA":
            if e[0][0] == "77" and summary:
                result["header"]["total_amount"] = numeric(e[0][1])
            elif e[0][0] == "203" and current:
                current["amount"] = numeric(e[0][1])
        elif tag == "CNT" and int(e[0][1]) != len(result["items"]):
            raise ValueError("ITEM_COUNT_MISMATCH")
    if kind == "INVOIC":
        result["invoice_no"] = result["document_no"]
    else:
        result["header"]["packages"] = package_sum
        result["header"]["total_amount"] = None
    result["header"]["quantity"] = sum(row["quantity"] for row in result["items"])
    return result


def compare_values(actual, expected, path=""):
    if isinstance(expected, dict):
        for key, value in expected.items():
            if key in {"file_name", "quantity_source", "packages_source"}:
                continue
            compare_values(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError(f"{path}: wrong list length")
        for i, (a, b) in enumerate(zip(actual, expected)):
            compare_values(a, b, f"{path}[{i}]")
    elif isinstance(actual, Decimal):
        if actual != Decimal(str(expected)):
            raise ValueError(f"{path}: numeric value mismatch")
    elif actual != expected:
        raise ValueError(f"{path}: {actual!r} != {expected!r}")


def validate(output: Path):
    expected = json.loads((output / "expected.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    failures, results = [], []
    file_map = {entry["path"]: entry for entry in manifest["files"]}
    matrix = json.loads((output / "first-batch-matrix.json").read_text(encoding="utf-8"))
    if {entry["path"] for entry in matrix["files"]} != set(file_map):
        failures.append("First-batch matrix inventory differs from manifest")
    if matrix["proposal_status"] != "PENDING_C_CONFIRMATION" or matrix["current_runtime_acceptance"] != "NOT_RUN":
        failures.append("Fixture matrix must not declare confirmed parser support or runtime acceptance")
    observed = {path.relative_to(output).as_posix() for path in output.rglob("*.edi")}
    if observed != set(file_map):
        failures.append("EDI file inventory differs from manifest")
    for relative, entry in file_map.items():
        content = (output / relative).read_bytes()
        if len(content) != entry["size_bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
            failures.append(f"{relative}: checksum or size mismatch")
    for case in expected["cases"]:
        messages_by_file, errors = {}, []
        for name in sorted({doc["file_name"] for doc in case["documents"].values()}):
            try:
                segments, decimal = decode((output / case["case_id"] / name).read_text(encoding="ascii"))
                messages, envelope_errors = envelopes(segments)
                errors.extend(envelope_errors)
                messages_by_file[name] = {msg[0][1][0][0]: (msg, decimal) for msg in messages}
            except (ValueError, IndexError, KeyError) as exc:
                errors.append(str(exc))
        if case["syntax_expected"] == "REJECT":
            needed = ({"MISSING_UNT", "MISSING_UNZ"} if case["expected_error"] == "MISSING_TRAILERS"
                      else {case["expected_error"]})
            passed = needed.issubset(set(errors))
        else:
            passed = not errors
            if passed:
                try:
                    for doc in case["documents"].values():
                        msg, decimal = messages_by_file[doc["file_name"]][doc["message_reference"]]
                        order_check(msg)
                        compare_values(business_read(msg, decimal), doc)
                except (ValueError, IndexError, KeyError) as exc:
                    errors.append(str(exc)); passed = False
        if not passed:
            failures.append(f"{case['case_id']}: {errors}")
        results.append(dict(case_id=case["case_id"], passed=passed,
                            syntax_expected=case["syntax_expected"], observed_errors=errors))
    return dict(passed=not failures, dataset_version=expected["dataset_version"], case_count=len(results),
                edi_file_count=len(file_map), limitations=["selected fixture-profile checks only",
                "not complete D.96A/MIG certification", "no current application EDI support or acceptance"],
                failures=failures, cases=results)
