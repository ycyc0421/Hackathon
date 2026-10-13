"""针对性回归测试：钉死比对/规则/抽取的关键边界，防止以后改代码时退化。

    python tools/test_compare.py

为什么单独写这个文件：三套示例单证并没有覆盖这些情形，光靠 selftest
证明不了。这里用合成数据直接打比对引擎与规则层，把边界固定下来。

覆盖：
  [1] 金额数值相同、币种不同 -> CONFLICT
  [2] 金额数值相同、币种没识别全 -> NOT_CHECKED（不能判 MATCH）
  [3] 规则未核实标记的闸门：只改 verified 不填核实人，不算已核实
  [4] 描述长文本里只差颜色词 -> CONFLICT（相似度掩盖不了）
  [5] 描述规格/容量数字不同 -> CONFLICT
  [6] 描述非关键差异（多一个「釉」字）-> 仍 MATCH
  [7] 正则抽取的 confidence 一律为 null
  [8] 多品名：表格区域必须从票级文本里剥掉（否则票级会抽到表头和行号）
  [9] 多品名：行序不同也要靠货号对齐上
  [10] 多品名：没有货号时按描述对齐；三份文件同品名要合成一组
  [11] 多品名：对齐确定不了 -> UNALIGNED，且绝不能产出 MATCH/CONFLICT
  [12] 多品名：一边多一行/少一行 -> PARTIAL，不合并、不丢弃
  [13] 多品名：装箱单本来就没有 HS 列 -> 不能报「缺失」

不依赖 pytest，直接用 assert；通过打印 ✓，失败抛 AssertionError。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.pipeline.compare import build_comparisons, build_item_comparisons  # noqa: E402
from app.pipeline.extract import extract_fields  # noqa: E402

PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        raise AssertionError(f"  ✗ {name}  {detail}")


def doc(file_id: str, name: str) -> dict:
    return {
        "file_id": file_id,
        "file_name": name,
        "file_type": "PDF",
        "doc_type": "COMMERCIAL_INVOICE",
        "process_status": "EXTRACTED",
        "page_count": 1,
        "error_message": None,
    }


def field(key: str, value, unit=None, status: str = "EXTRACTED") -> dict:
    return {
        "field_key": key,
        "label": key,
        "raw_text": None,
        "raw_value": None,
        "normalized_value": value,
        "unit": unit,
        "confidence": None,
        "status": status,
        "page": 1,
        "bbox": None,
        "bbox_unit": None,
    }


def extraction(file_id: str, fields: list[dict]) -> dict:
    return {"file_id": file_id, "doc_type": "COMMERCIAL_INVOICE", "parse_method": "TEXT_LAYER", "fields": fields}


def find(comparisons: list[dict], key: str) -> dict | None:
    return next((c for c in comparisons if c["field_key"] == key), None)


def no_hs(_code, _hs) -> bool:
    """所有 HS 都当作「未被规则覆盖」，避免测试依赖规则库内容。"""
    return False


# --------------------------------------------------------------------------
# 1) 金额比对必须同时看币种
# --------------------------------------------------------------------------
def test_money_currency() -> None:
    print("\n[1] 金额：数值相同但币种不同，不能判为一致")
    docs = [doc("f1", "发票.pdf"), doc("f2", "装箱单.pdf")]

    exts = [
        extraction("f1", [field("total_amount", 12500, unit="USD"), field("currency", "USD")]),
        extraction("f2", [field("total_amount", 12500, unit="EUR"), field("currency", "EUR")]),
    ]
    cmps = build_comparisons(docs, exts, no_hs, "DE", "德国")
    amount = find(cmps, "total_amount")
    check("100 USD vs 100 EUR 判为 CONFLICT", amount["status"] == "CONFLICT", str(amount))
    check("金额冲突 severity=ERROR", amount["severity"] == "ERROR", str(amount["severity"]))
    check("note 指出是币种不一致", "币种" in (amount["note"] or ""), str(amount["note"]))
    check("币种不一致时 unit 置 null", amount["unit"] is None, str(amount["unit"]))

    # 对照组：币种与数值都相同 -> MATCH
    exts2 = [
        extraction("f1", [field("total_amount", 12500, unit="USD")]),
        extraction("f2", [field("total_amount", 12500, unit="USD")]),
    ]
    amount2 = find(build_comparisons(docs, exts2, no_hs), "total_amount")
    check("同币种同数值 -> MATCH", amount2["status"] == "MATCH", str(amount2))
    check("同币种时 unit 为 USD", amount2["unit"] == "USD", str(amount2["unit"]))


# --------------------------------------------------------------------------
# 2) 金额：币种没识别全 -> 无法确认，不能判 MATCH
# --------------------------------------------------------------------------
def test_money_currency_unknown() -> None:
    print("\n[2] 金额：一份有币种、一份没识别出币种 -> 不能判 MATCH")
    docs = [doc("f1", "发票.pdf"), doc("f2", "装箱单.pdf")]

    # 发票有 USD，装箱单金额识别到了但币种没识别出来
    exts = [
        extraction("f1", [field("total_amount", 12500, unit="USD"), field("currency", "USD")]),
        extraction(
            "f2",
            [field("total_amount", 12500, unit=None), field("currency", None, status="MISSING_IN_DOC")],
        ),
    ]
    amount = find(build_comparisons(docs, exts, no_hs, "DE", "德国"), "total_amount")
    check("币种不全 -> NOT_CHECKED（不是 MATCH）", amount["status"] == "NOT_CHECKED", str(amount))
    check("note 说明未识别出币种", "币种" in (amount["note"] or ""), str(amount["note"]))
    check("severity=WARNING", amount["severity"] == "WARNING", str(amount["severity"]))

    # 两份都没币种 -> 同样无法确认
    exts2 = [
        extraction("f1", [field("total_amount", 12500, unit=None)]),
        extraction("f2", [field("total_amount", 12500, unit=None)]),
    ]
    amount2 = find(build_comparisons(docs, exts2, no_hs), "total_amount")
    check("两份都没币种 -> NOT_CHECKED", amount2["status"] == "NOT_CHECKED", str(amount2))


# --------------------------------------------------------------------------
# 3) 规则未核实的闸门：光改 verified 不算数
# --------------------------------------------------------------------------
def test_rules_unverified_guard() -> None:
    print("\n[3] 规则：未核实标记的闸门")
    from app.pipeline import rules

    check("当前规则集未核实（verified=false）", rules.ruleset_verified() is False)

    original = rules.load_rules
    try:
        rules.load_rules = lambda: {"version": "x", "verified": True, "verified_by": None}
        check("只把 verified 改成 true、不填核实人 -> 仍算未核实", rules.ruleset_verified() is False)
        rules.load_rules = lambda: {"version": "x", "verified": True, "verified_by": "C-某人"}
        check("核实日期缺失 -> 仍算未核实", rules.ruleset_verified() is False)
        rules.load_rules = lambda: {"version": "x", "verified": True, "verified_by": "C-某人", "verified_at": "2026-10-12"}
        check("verified=true 且核实人、日期完整 -> 才算已核实", rules.ruleset_verified() is True)
    finally:
        rules.load_rules = original



# --------------------------------------------------------------------------
# 4) 货物描述：关键属性差异不能被相似度掩盖
# --------------------------------------------------------------------------
def _desc_comparison(d1: str, d2: str) -> dict:
    docs = [doc("f1", "发票.pdf"), doc("f2", "装箱单.pdf")]
    exts = [
        extraction("f1", [field("description", d1)]),
        extraction("f2", [field("description", d2)]),
    ]
    return find(build_comparisons(docs, exts, no_hs), "description")


def test_description_critical_token() -> None:
    print("\n[4] 描述：长描述里只差一个颜色词，仍要判 CONFLICT")
    base = "陶瓷 马克杯 350ML 食品级 加厚 出口 包装 白"
    other = "陶瓷 马克杯 350ML 食品级 加厚 出口 包装 红"
    # 先确认这种情形相似度确实高于阈值（否则测不出「闸门」的作用）
    from app.pipeline.compare import _similarity, _SIMILARITY_THRESHOLD

    sim = _similarity(base, other)
    check(
        f"相似度 {sim:.3f} 高于阈值 {_SIMILARITY_THRESHOLD}（差异会被掩盖）",
        sim >= _SIMILARITY_THRESHOLD,
        f"sim={sim}",
    )
    cmp = _desc_comparison(base, other)
    check("颜色不同 -> CONFLICT", cmp["status"] == "CONFLICT", str(cmp))
    check("note 指出关键属性差异", "关键属性" in (cmp["note"] or ""), str(cmp["note"]))


def test_description_spec_digit() -> None:
    print("\n[5] 描述：规格/容量数字不同，仍要判 CONFLICT")
    cmp = _desc_comparison(
        "陶瓷 马克杯 350ML 白 食品级 加厚 出口 包装",
        "陶瓷 马克杯 500ML 白 食品级 加厚 出口 包装",
    )
    check("容量 350ML vs 500ML -> CONFLICT", cmp["status"] == "CONFLICT", str(cmp))


def test_description_fuzzy_ok() -> None:
    print("\n[6] 描述：非关键差异（多一个『釉』字）仍应判 MATCH")
    cmp = _desc_comparison("陶瓷 马克杯 350ML 白", "陶瓷 马克杯 350ML 白 釉")
    check("写法不同但同一件货 -> MATCH", cmp["status"] == "MATCH", str(cmp))


# --------------------------------------------------------------------------
# 7) confidence 诚实性：正则抽出的字段不给伪造数字
# --------------------------------------------------------------------------
def test_confidence_is_null() -> None:
    print("\n[7] confidence：正则通道一律 null，不用假数字")
    text = (
        "COMMERCIAL INVOICE\n"
        "INVOICE NO.: INV-2026-1012\n"
        "DESCRIPTION OF GOODS: CERAMIC MUG 350ML WHITE\n"
        "PACKAGES: 120 CARTONS\n"
        "G.W.: 2,400.00 KGS\n"
        "TOTAL: USD 12,500.00\n"
    )
    fields = extract_fields(text, "COMMERCIAL_INVOICE", page=1)
    extracted = [f for f in fields if f["status"] in ("EXTRACTED", "LOW_CONFIDENCE")]
    check("确实抽出了字段（否则测试没意义）", len(extracted) >= 3, str(len(extracted)))
    check(
        "所有已抽出字段的 confidence 均为 null",
        all(f["confidence"] is None for f in extracted),
        str([(f["field_key"], f["confidence"]) for f in extracted]),
    )
    check(
        "未抽出字段的 confidence 也为 null",
        all(f["confidence"] is None for f in fields),
        "存在非 null",
    )


# --------------------------------------------------------------------------
# 多品名（v0.2）：行切分 / 跨文件对齐 / 品名级比对
# --------------------------------------------------------------------------
TABLE_TEXT = (
    "COMMERCIAL INVOICE\n"
    "INVOICE NO.: INV-1\n"
    "NO.  ITEM NO.  DESCRIPTION             HS CODE     QTY       PACKAGES    G.W.\n"
    "1    HM-1001   CERAMIC MUG 350ML WHITE 6911.10.00  1200 PCS  60 CARTONS  1200.00 KGS\n"
    "2    HM-1002   CERAMIC PLATE 20CM BLUE 6912.00.00  800 PCS   40 CARTONS  960.00 KGS\n"
    "TOTAL PACKAGES: 100 CARTONS\n"
)


def row(item_no: int, fields: list[dict]) -> dict:
    return {"item_no": item_no, "raw_text": None, "fields": fields}


def rows_extraction(file_id: str, rows: list[dict]) -> dict:
    return {
        "file_id": file_id,
        "doc_type": "COMMERCIAL_INVOICE",
        "parse_method": "TEXT_LAYER",
        "fields": [],
        "line_items": rows,
    }


def test_table_stripped() -> None:
    print("\n[8] 多品名：表格必须从票级文本里剥掉")
    from app.pipeline.rows import parse_line_items

    t = parse_line_items(TABLE_TEXT)
    check("认出 2 个品名行", len(t.line_items) == 2, str(len(t.line_items)))
    check("表头没残留进票级文本", "ITEM NO." not in t.doc_text, t.doc_text)
    check("品名行没残留进票级文本", "HM-1001" not in t.doc_text, t.doc_text)
    check("合计行保留给票级", "TOTAL PACKAGES: 100" in t.doc_text, t.doc_text)

    fields = extract_fields(t.doc_text, "COMMERCIAL_INVOICE", page=1, row_keys=t.header_keys)
    by_key = {f["field_key"]: f for f in fields}
    check("票级件数取到合计值 100", by_key["packages"]["normalized_value"] == 100, str(by_key["packages"]))
    # 剥掉之前，票级会把行号当总金额（实测踩过的 bug）
    check(
        "票级总金额不再抓到行号",
        by_key["total_amount"]["normalized_value"] is None,
        str(by_key["total_amount"]),
    )
    check(
        "按行提供的字段在票级报 NOT_IN_DOC（不是 MISSING）",
        by_key["description"]["status"] == "NOT_IN_DOC",
        str(by_key["description"]["status"]),
    )


def test_align_by_code_any_order() -> None:
    print("\n[9] 多品名：行序不同也要靠货号对齐")
    from app.pipeline.align import align_items

    docs = [doc("f1", "发票.pdf"), doc("f2", "装箱单.pdf")]
    exts = [
        rows_extraction(
            "f1",
            [
                row(1, [field("item_code", "HM-1001"), field("description", "陶瓷 马克杯 350ML 白"), field("packages", 60, "CARTON")]),
                row(2, [field("item_code", "HM-1002"), field("description", "陶瓷 盘 20CM 蓝"), field("packages", 40, "CARTON")]),
            ],
        ),
        rows_extraction(
            "f2",
            [
                row(1, [field("item_code", "HM-1002"), field("description", "陶瓷 盘 20CM 蓝"), field("packages", 45, "CARTON")]),
                row(2, [field("item_code", "HM-1001"), field("description", "陶瓷 马克杯 350ML 白"), field("packages", 60, "CARTON")]),
            ],
        ),
    ]
    items = align_items(exts, docs)
    check("对齐出 2 个行组", len(items) == 2, str(items))
    check("全部 ALIGNED", all(i["alignment_status"] == "ALIGNED" for i in items), str(items))
    check("依据是货号", all(i["alignment_basis"] == "ITEM_CODE" for i in items), str(items))

    mug = next(i for i in items if "马克杯" in i["label"])
    members = {(m["file_id"], m["item_no"]) for m in mug["members"]}
    check("发票第 1 行对上了装箱单第 2 行", members == {("f1", 1), ("f2", 2)}, str(members))
    check("货号一致时 match_score=1.0", all(m["match_score"] == 1.0 for m in mug["members"]), str(mug["members"]))

    cmps = build_item_comparisons(items, docs, exts, no_hs, "DE", "德国")
    pack = find(cmps, "packages")
    check("品名级件数 60 vs 60 -> MATCH", pack is not None and pack["status"] == "MATCH", str(pack))
    check("品名级比对带 scope=ITEM 与 item_id", pack["scope"] == "ITEM" and pack["item_id"], str(pack))
    conflicts = [c for c in cmps if c["status"] == "CONFLICT"]
    check(
        "盘子件数 40 vs 45 -> CONFLICT",
        len(conflicts) == 1 and conflicts[0]["field_key"] == "packages",
        str(conflicts),
    )
    check("票级比对不受影响（没有同名字段混入）", all(c["scope"] == "ITEM" for c in cmps), "存在非 ITEM 条目")


def test_align_by_description() -> None:
    print("\n[10] 多品名：无货号时按描述对齐，三份文件同品名合成一组")
    from app.pipeline.align import align_items

    docs = [doc("f1", "A.pdf"), doc("f2", "B.pdf"), doc("f3", "C.pdf")]
    exts = [
        rows_extraction("f1", [row(1, [field("description", "陶瓷 马克杯 350ML 白")])]),
        rows_extraction("f2", [row(1, [field("description", "陶瓷 马克杯 350ML 白")])]),
        rows_extraction("f3", [row(1, [field("description", "陶瓷 马克杯 350ML")])]),
    ]
    items = align_items(exts, docs)
    check("三份文件合成 1 个行组", len(items) == 1, str(items))
    check("依据是描述", items[0]["alignment_basis"] == "DESCRIPTION", str(items[0]))
    check("三个成员都在同一组", len(items[0]["members"]) == 3, str(items[0]["members"]))
    check("状态为 ALIGNED", items[0]["alignment_status"] == "ALIGNED", str(items[0]))
    check("ALIGNED 时 alignment_note 为 null", items[0]["alignment_note"] is None, str(items[0]))


def test_unresolved_never_concludes() -> None:
    print("\n[11] 多品名：对齐确定不了 -> 只给 NOT_CHECKED，绝不给结论")
    from app.pipeline.align import align_items

    docs = [doc("f1", "A.pdf"), doc("f2", "B.pdf")]
    exts = [
        rows_extraction(
            "f1",
            [
                row(1, [field("description", "陶瓷 杯 350ML 白"), field("packages", 10, "CARTON")]),
                row(2, [field("description", "陶瓷 杯 350ML 黑"), field("packages", 20, "CARTON")]),
            ],
        ),
        rows_extraction("f2", [row(1, [field("description", "陶瓷 杯 350ML"), field("packages", 30, "CARTON")])]),
    ]
    items = align_items(exts, docs)
    check("没有硬凑成 ALIGNED", not [i for i in items if i["alignment_status"] == "ALIGNED"], str(items))
    check("确实有 UNALIGNED 行组", any(i["alignment_status"] == "UNALIGNED" for i in items), str(items))
    for i in items:
        if i["alignment_status"] in ("UNALIGNED", "PARTIAL"):
            check(f"{i['item_id']} 对不上时必须给出原因", bool(i["alignment_note"]), str(i))

    cmps = build_item_comparisons(items, docs, exts, no_hs, "DE", "德国")
    bad = [c for c in cmps if c["status"] in ("MATCH", "CONFLICT")]
    check("对不上的行组不得产出 MATCH / CONFLICT", not bad, str(bad))
    unaligned_ids = {i["item_id"] for i in items if i["alignment_status"] == "UNALIGNED"}
    hit = [c for c in cmps if c["item_id"] in unaligned_ids]
    check("UNALIGNED 行组有产出比对条目（不是静默省略）", bool(hit), "没有条目")
    check("UNALIGNED 行组一律 NOT_CHECKED", all(c["status"] == "NOT_CHECKED" for c in hit), str(hit))
    check("NOT_CHECKED 都带 note", all(c["note"] for c in hit), str(hit))


def test_partial_groups() -> None:
    print("\n[12] 多品名：一边多一行/少一行 -> PARTIAL，不合并、不丢弃")
    from app.pipeline.align import align_items

    docs = [doc("f1", "发票.pdf"), doc("f2", "装箱单.pdf")]
    exts = [
        rows_extraction(
            "f1",
            [
                row(1, [field("item_code", "HM-1001"), field("description", "陶瓷 马克杯 白")]),
                row(2, [field("item_code", "HM-1002"), field("description", "陶瓷 盘 蓝")]),
            ],
        ),
        rows_extraction(
            "f2",
            [
                row(1, [field("item_code", "HM-1001"), field("description", "陶瓷 马克杯 白")]),
                row(2, [field("item_code", "HM-1009"), field("description", "陶瓷 碟 白")]),
            ],
        ),
    ]
    items = align_items(exts, docs)
    check("共 3 个行组（1 组对齐 + 2 组单边）", len(items) == 3, str(items))
    check("对齐的那组是 ALIGNED", len([i for i in items if i["alignment_status"] == "ALIGNED"]) == 1, str(items))
    partials = [i for i in items if i["alignment_status"] == "PARTIAL"]
    check("两组单边的都是 PARTIAL", len(partials) == 2, str(items))
    check("单边行组只有一个成员", all(len(i["members"]) == 1 for i in partials), str(partials))
    check(
        "每一行都出现在某个行组里（没有行被丢掉）",
        sorted((m["file_id"], m["item_no"]) for i in items for m in i["members"])
        == [("f1", 1), ("f1", 2), ("f2", 1), ("f2", 2)],
        str(items),
    )


def test_row_field_not_applicable() -> None:
    print("\n[13] 多品名：装箱单本来就没有 HS 列 -> 不能报「缺失」")
    from app.pipeline.align import align_items

    docs = [doc("f1", "发票.pdf"), doc("f2", "装箱单.pdf")]
    exts = [
        rows_extraction("f1", [row(1, [field("item_code", "HM-1001"), field("hs_code", "69111000")])]),
        rows_extraction(
            "f2",
            [row(1, [field("item_code", "HM-1001"), field("hs_code", None, status="NOT_IN_DOC")])],
        ),
    ]
    items = align_items(exts, docs)
    cmps = build_item_comparisons(items, docs, exts, no_hs, "DE", "德国")
    hs = find(cmps, "hs_code")
    check("HS 只在一份文件里适用 -> SINGLE_SOURCE", hs["status"] == "SINGLE_SOURCE", str(hs))
    check("不是 MISSING_IN_SOME（那会把正常差异报成缺失）", hs["status"] != "MISSING_IN_SOME", str(hs))
    check("note 说明了是哪一份文件", "发票" in (hs["note"] or ""), str(hs["note"]))
    check("NOT_IN_DOC 的那份不进 values", len(hs["values"]) == 1, str(hs["values"]))


def main() -> int:
    test_money_currency()
    test_money_currency_unknown()
    test_rules_unverified_guard()
    test_description_critical_token()
    test_description_spec_digit()
    test_description_fuzzy_ok()
    test_confidence_is_null()
    test_table_stripped()
    test_align_by_code_any_order()
    test_align_by_description()
    test_unresolved_never_concludes()
    test_partial_groups()
    test_row_field_not_applicable()
    print(f"\n全部通过（{PASSED} 项断言）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
