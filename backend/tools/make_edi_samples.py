"""Generate deterministic, synthetic UN/EDIFACT D.96A regression inputs.

No runtime parser, upload, deployment or existing sample is changed. The checker
is a limited fixture reader, not a complete EDIFACT or trading-partner validator.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "samples" / "edi"
REFERENCE = "https://service.unece.org/trade/untdid/d96a/"


def number(value, decimal="."):
    return format(Decimal(str(value)), "f").replace(".", decimal)


class Writer:
    def __init__(self, decimal=".", compact=False):
        self.decimal, self.compact = decimal, compact

    def escape(self, value):
        return "".join("?" + ch if ch in ":+?'" else ch for ch in str(value))

    def segment(self, tag, *elements):
        return tag + "".join("+" + (":".join(self.escape(v) for v in e)
                             if isinstance(e, tuple) else self.escape(e)) for e in elements) + "'"

    def envelope(self, messages, reference):
        parts = ["UNA:+" + self.decimal + "? '",
                 self.segment("UNB", ("UNOC", "3"), "SYNTHETIC-SENDER", "SYNTHETIC-RECEIVER",
                              ("261012", "1200"), reference)]
        for message in messages:
            parts.extend(message)
        parts.append(self.segment("UNZ", len(messages), reference))
        return ("" if self.compact else "\n").join(parts) + "\n"


def item(code="MUG350", description="CERAMIC MUG 350ML WHITE", hs="691110",
         qty=2400, packages=100, net="900.00", gross="1080.00", price="2.00", volume="4.80"):
    return dict(item_code=code, description=description, hs_code=hs, quantity=qty,
                packages=packages, net_weight=net, gross_weight=gross, unit_price=price, volume=volume)


def document(kind, case, items, country="DE", currency="USD", role="original"):
    return dict(message_type=kind, document_no=f"SYN-{kind}-{case:02d}",
                order_no=f"SYN-ORDER-{case:02d}", invoice_no=f"SYN-INVOIC-{case:02d}",
                destination_country=country, currency=currency if kind == "INVOIC" else None,
                document_date="2026-10-12", shipment_date="2026-10-14", role=role,
                items=deepcopy(items))


def totals(doc):
    rows = doc["items"]
    return {"packages": sum(row["packages"] for row in rows),
            "quantity": sum(row["quantity"] for row in rows),
            **{key: format(sum(Decimal(row[key]) for row in rows), "f")
               for key in ("net_weight", "gross_weight", "volume")}}


def monetary_total(doc):
    return format(sum(Decimal(row["unit_price"]) * row["quantity"] for row in doc["items"]), ".2f")


def message(doc, writer, reference):
    s = writer.segment
    n = lambda value: number(value, writer.decimal)
    kind = doc["message_type"]
    values = totals(doc)
    segments = [s("UNH", reference, (kind, "D", "96A", "UN")),
                s("BGM", "380" if kind == "INVOIC" else "351", doc["document_no"],
                  "7" if doc["role"] == "copy" else "9"),
                s("DTM", ("137", "20261012", "102")), s("DTM", ("11", "20261014", "102"))]
    if kind == "INVOIC":
        segments.append(s("FTX", "AAI", "", "", "SYNTHETIC TEST DATA - NOT FOR CUSTOMS OR PAYMENT"))
    else:
        for qualifier, key, unit in [("AAD", "gross_weight", "KGM"),
                                     ("AAC", "net_weight", "KGM"), ("AAW", "volume", "MTQ")]:
            segments.append(s("MEA", "AAE", qualifier, (unit, n(values[key]))))
    segments.append(s("RFF", ("ON", doc["order_no"])))
    if kind == "DESADV":
        segments.append(s("RFF", ("IV", doc["invoice_no"])))
    for qualifier, name, country in [("CZ", "SYNTHETIC SUPPLIER LTD", "CN"),
                                      ("CN", "SYNTHETIC BUYER LTD", doc["destination_country"])]:
        segments.append(s("NAD", qualifier, "", "", name, "1 TEST ROAD", "TESTCITY", "", "00000", country))
    if kind == "INVOIC":
        if doc["currency"]:
            segments.append(s("CUX", ("2", doc["currency"], "4")))
        segments.append(s("PAC", values["packages"], "", "CT"))
        for qualifier, key, unit in [("AAD", "gross_weight", "KGM"),
                                     ("AAC", "net_weight", "KGM"), ("AAW", "volume", "MTQ")]:
            segments.append(s("MEA", "AAE", qualifier, (unit, n(values[key]))))
    for index, row in enumerate(doc["items"], 1):
        if kind == "DESADV":
            segments += [s("CPS", index), s("PAC", row["packages"], "", "CT")]
        segments.append(s("LIN", index, "", (row["item_code"], "SA")))
        if row["hs_code"]:
            segments.append(s("PIA", "1", (row["hs_code"], "HS")))
        segments.append(s("IMD", "F", "", ("", "", "", row["description"])))
        for qualifier, key in [("AAE", "gross_weight"), ("AAL", "net_weight")]:
            segments.append(s("MEA", "AAE", qualifier, ("KGM", n(row[key]))))
        segments.append(s("QTY", ("47" if kind == "INVOIC" else "12", row["quantity"], "PCE")))
        if kind == "INVOIC":
            amount = Decimal(row["unit_price"]) * row["quantity"]
            segments += [s("MOA", ("203", n(amount))),
                         s("PRI", ("AAA", n(row["unit_price"]), "", "", "1", "PCE")),
                         s("PAC", row["packages"], "", "CT")]
    if kind == "INVOIC":
        segments += [s("UNS", "S"), s("CNT", ("2", len(doc["items"]))),
                     s("MOA", ("77", n(monetary_total(doc))))]
    else:
        segments.append(s("CNT", ("2", len(doc["items"]))))
    segments.append(s("UNT", len(segments) + 1, reference))
    return segments


def expected_document(doc):
    result = deepcopy(doc)
    result.pop("role")
    result["header"] = totals(doc)
    result["header"]["total_amount"] = monetary_total(doc) if doc["message_type"] == "INVOIC" else None
    result["header"]["quantity_source"] = "sum_of_line_quantities"
    result["header"]["packages_source"] = ("header_PAC" if doc["message_type"] == "INVOIC"
                                              else "sum_of_CPS_package_groups")
    for index, row in enumerate(result["items"], 1):
        row["line_no"] = index
        row["quantity_unit"], row["weight_unit"], row["package_unit"] = "PCE", "KGM", "CT"
        row.pop("volume")  # only whole-message volume is explicitly emitted
        if doc["message_type"] == "INVOIC":
            row["amount"] = format(Decimal(row["unit_price"]) * row["quantity"], ".2f")
        else:
            row["unit_price"], row["amount"] = None, None
    return result


def build_cases():
    base = [item()]
    def pair(case, country="DE", rows=None):
        return [document("INVOIC", case, rows or base, country), document("DESADV", case, rows or base, country)]
    cases = []
    def add(case_id, title, docs, notes, **options):
        cases.append(dict(case_id=case_id, title=title, documents=docs, notes=notes, **options))
    add("01_consistent", "单商品一致", pair(1, "US"), "数量、包装、重量、HS 一致；金额只由发票提供。")
    docs = pair(2); docs[1]["items"][0]["quantity"] = 2380
    add("02_quantity_conflict", "数量冲突", docs, "发票 2400 PCE，发运通知 2380 PCE；件数仍均为 100 CT。")
    docs = pair(3)
    row = docs[1]["items"][0]; row["net_weight"], row["gross_weight"] = row["gross_weight"], row["net_weight"]
    add("03_net_gross_swapped", "净毛重填反", docs, "发运通知故意交换净毛重；报文语法有效但业务值错误，净重超过毛重。")
    docs = pair(4); copy = deepcopy(docs[0]); copy["role"] = "copy"; copy["items"][0]["unit_price"] = "2.10"; docs.insert(1, copy)
    add("04_amount_conflict", "发票金额冲突", docs, "同发票号的原件与副本：单价 2.00/2.10，总金额 4800.00/5040.00。")
    docs = pair(5); copy = deepcopy(docs[0]); copy["role"] = "copy"; copy["currency"] = "EUR"; docs.insert(1, copy)
    add("05_currency_conflict", "数值相同币种不同", docs, "同发票号原件 USD、副本 EUR；不能因数字相同判断金额一致。")
    docs = pair(6); docs[0]["currency"] = None; docs[0]["items"][0]["hs_code"] = None
    add("06_missing_hs_currency", "HS 与币种未提供", docs, "发票省略 HS 和币种；不得从发运通知复制进发票字段，不得默认 USD。")
    rows = [item(qty=1200, packages=50, net="450.00", gross="540.00", volume="2.40"),
            item("BWL160", "CERAMIC BOWL 160MM BLUE", "691200", 600, 25, "180.00", "216.00", "3.50", "1.20"),
            item("BOT750", "GLASS BOTTLE 750ML CLEAR", "701090", 300, 15, "120.00", "144.00", "4.00", "0.90")]
    docs = pair(7, "NL", rows); docs[1]["items"] = [docs[1]["items"][2], docs[1]["items"][0], docs[1]["items"][1]]
    add("07_multiitem_reordered", "三商品行顺序不同", docs, "以货号关联，不能按 LIN 序号配对；票级总重量不得复制给每行。")
    rows = [item(description="GIFT SET + CUP: 350ML? WHITE'S")]
    add("08_release_characters", "保留字符转义", pair(8, "GB", rows), "描述包含加号、冒号、问号和撇号；须正确处理 EDIFACT release 字符。")
    rows = [item(net="900.25", gross="1080.50", price="2.05", volume="4.85")]
    add("09_decimal_comma_compact", "逗号小数与紧凑报文", pair(9, "FR", rows), "UNA 指定逗号小数；无行间换行，不能用换行切段。", decimal=",", compact=True)
    add("10_multi_message", "一个封装内两份报文", pair(10, "US"), "同一 UNB/UNZ 中有 INVOIC 与 DESADV，UNZ 消息数为 2。", combined=True)
    add("11_bad_unt_count", "故意错误的 UNT 段计数", [document("INVOIC", 11, base)], "语法负例：UNT 段计数被故意加一，必须显式拒绝。", invalid="UNT_COUNT_MISMATCH")
    add("12_truncated", "故意截断报文", [document("DESADV", 12, base)], "语法负例：缺少 UNT 和 UNZ，不得作为空结果或零冲突。", invalid="MISSING_TRAILERS")
    return cases


def discrepancies(documents):
    """Authoring-level expectations; never obtained from the application API."""
    result = []
    for key in ("quantity", "packages", "net_weight", "gross_weight", "total_amount"):
        values = {name: doc["header"][key] for name, doc in documents.items() if doc["header"][key] is not None}
        if key == "total_amount":
            values = {name: {"value": value, "currency": documents[name]["currency"]} for name, value in values.items()}
        if len({json.dumps(value, sort_keys=True) for value in values.values()}) > 1:
            result.append(dict(scope="SHIPMENT", field_key=key, values=values))
    currencies = {name: doc["currency"] for name, doc in documents.items() if doc["currency"]}
    if len(set(currencies.values())) > 1:
        result.append(dict(scope="SHIPMENT", field_key="currency", values=currencies))
    codes = sorted({row["item_code"] for doc in documents.values() for row in doc["items"]})
    for code in codes:
        for key in ("quantity", "packages", "net_weight", "gross_weight", "hs_code", "description", "unit_price", "amount"):
            values = {name: row[key] for name, doc in documents.items() for row in doc["items"]
                      if row["item_code"] == code and row.get(key) is not None}
            if key in {"unit_price", "amount"}:
                values = {name: {"value": value, "currency": documents[name]["currency"]} for name, value in values.items()}
            if len({json.dumps(value, sort_keys=True) for value in values.values()}) > 1:
                result.append(dict(scope="ITEM", item_code=code, field_key=key, values=values))
    return result


def write_json(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def first_batch_matrix(expected):
    files = []
    for case in expected["cases"]:
        for name in sorted({doc["file_name"] for doc in case["documents"].values()}):
            docs = [doc for doc in case["documents"].values() if doc["file_name"] == name]
            if len(docs) > 1:
                proposal = "OUT_OF_SCOPE_MULTIPLE_UNH"
            elif docs[0]["message_type"] != "INVOIC":
                proposal = "OUT_OF_SCOPE_MESSAGE_TYPE"
            elif case["syntax_expected"] == "REJECT":
                proposal = "REJECT_INVALID_MESSAGE"
            else:
                proposal = "IN_SCOPE_PENDING_C_CONFIRMATION"
            files.append(dict(path=case["case_id"] + "/" + name,
                              message_types=[doc["message_type"] for doc in docs],
                              authored_message_count=len(docs), fixture_syntax_expected=case["syntax_expected"],
                              proposed_first_batch_expectation=proposal,
                              specific_error_code="PENDING_C_F_CONTRACT", encoding="ASCII / UTF-8 subset; no BOM"))
    return dict(proposal_status="PENDING_C_CONFIRMATION",
                source="https://github.com/ycyc0421/Hackathon/issues/40#issuecomment-6123316495",
                proposed_message_type="INVOIC:D:96A:UN", maximum_messages_per_file=1,
                current_runtime_acceptance="NOT_RUN", files=files)


def generate(output):
    output.mkdir(parents=True, exist_ok=True)
    expected = dict(dataset_version="edi-synthetic-v1", synthetic=True, directory="D.96A",
                    business_acceptance=False, current_api_support=False, cases=[])
    for case_no, case in enumerate(build_cases(), 1):
        folder = output / case["case_id"]
        folder.mkdir(exist_ok=True)
        writer = Writer(case.get("decimal", "."), case.get("compact", False))
        doc_entries = {}
        messages = []
        for index, doc in enumerate(case["documents"], 1):
            name = f"{index:02d}_{doc['message_type'].lower()}{'_copy' if doc['role'] == 'copy' else ''}.edi"
            entry = expected_document(doc)
            entry["file_name"] = "shipment.edi" if case.get("combined") else name
            entry["message_reference"] = f"{case_no:02d}{index:02d}"
            doc_entries[f"doc_{index}"] = entry
            message_segments = message(doc, writer, entry["message_reference"])
            messages.append(message_segments)
            if not case.get("combined"):
                if case.get("invalid") == "UNT_COUNT_MISMATCH":
                    message_segments[-1] = writer.segment("UNT", len(message_segments) + 1, entry["message_reference"])
                text = writer.envelope([message_segments], f"SYN{case_no:02d}{index:02d}")
                if case.get("invalid") == "MISSING_TRAILERS":
                    text = "\n".join(text.splitlines()[:-2]) + "\n"
                (folder / name).write_bytes(text.encode("ascii"))
        if case.get("combined"):
            (folder / "shipment.edi").write_bytes(writer.envelope(messages, f"SYN{case_no:02d}00").encode("ascii"))
        expected["cases"].append(dict(case_id=case["case_id"], title=case["title"], notes=case["notes"],
                                      syntax_expected="REJECT" if case.get("invalid") else "ACCEPT",
                                      expected_error=case.get("invalid"), documents=doc_entries,
                                      expected_discrepancies=discrepancies(doc_entries)))
    write_json(output / "expected.json", expected)
    write_json(output / "first-batch-matrix.json", first_batch_matrix(expected))
    manifest = []
    for path in sorted(output.rglob("*.edi")):
        content = path.read_bytes()
        manifest.append(dict(path=path.relative_to(output).as_posix(), size_bytes=len(content),
                             sha256=hashlib.sha256(content).hexdigest()))
    write_json(output / "manifest.json", dict(dataset_version=expected["dataset_version"], files=manifest))
    return len(expected["cases"]), len(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="validate existing files without rewriting them")
    args = parser.parse_args()
    if not args.check:
        count, files = generate(args.output)
        print(f"Generated {count} synthetic cases, {files} EDI files: {args.output.resolve()}")
    from validate_edi_samples import validate
    report = validate(args.output)
    write_json(args.output / "validation-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
