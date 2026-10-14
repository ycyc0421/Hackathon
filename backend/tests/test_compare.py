"""针对性回归测试：钉死比对/规则/抽取的关键边界，防止以后改代码时退化。

    python -m pytest backend/tests/test_compare.py

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

每个行为独立收集，失败时由测试框架报告断言上下文。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.pipeline.compare import build_comparisons, build_item_comparisons  # noqa: E402
from app.pipeline.extract import extract_fields  # noqa: E402

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


def _desc_comparison(d1: str, d2: str) -> dict:
    docs = [doc("f1", "发票.pdf"), doc("f2", "装箱单.pdf")]
    exts = [
        extraction("f1", [field("description", d1)]),
        extraction("f2", [field("description", d2)]),
    ]
    return find(build_comparisons(docs, exts, no_hs), "description")


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


class ComparisonTests(unittest.TestCase):
    def test_money_currency(self) -> None:
        docs = [doc("f1", "发票.pdf"), doc("f2", "装箱单.pdf")]

        exts = [
            extraction("f1", [field("total_amount", 12500, unit="USD"), field("currency", "USD")]),
            extraction("f2", [field("total_amount", 12500, unit="EUR"), field("currency", "EUR")]),
        ]
        cmps = build_comparisons(docs, exts, no_hs, "DE", "德国")
        amount = find(cmps, "total_amount")
        assert (amount["status"] == "CONFLICT"), ("100 USD vs 100 EUR 判为 CONFLICT", str(amount))
        assert (amount["severity"] == "ERROR"), ("金额冲突 severity=ERROR", str(amount["severity"]))
        assert ("币种" in (amount["note"] or "")), ("note 指出是币种不一致", str(amount["note"]))
        assert (amount["unit"] is None), ("币种不一致时 unit 置 null", str(amount["unit"]))

        # 对照组：币种与数值都相同 -> MATCH
        exts2 = [
            extraction("f1", [field("total_amount", 12500, unit="USD")]),
            extraction("f2", [field("total_amount", 12500, unit="USD")]),
        ]
        amount2 = find(build_comparisons(docs, exts2, no_hs), "total_amount")
        assert (amount2["status"] == "MATCH"), ("同币种同数值 -> MATCH", str(amount2))
        assert (amount2["unit"] == "USD"), ("同币种时 unit 为 USD", str(amount2["unit"]))

    def test_money_currency_unknown(self) -> None:
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
        assert (amount["status"] == "NOT_CHECKED"), ("币种不全 -> NOT_CHECKED（不是 MATCH）", str(amount))
        assert ("币种" in (amount["note"] or "")), ("note 说明未识别出币种", str(amount["note"]))
        assert (amount["severity"] == "WARNING"), ("severity=WARNING", str(amount["severity"]))

        # 两份都没币种 -> 同样无法确认
        exts2 = [
            extraction("f1", [field("total_amount", 12500, unit=None)]),
            extraction("f2", [field("total_amount", 12500, unit=None)]),
        ]
        amount2 = find(build_comparisons(docs, exts2, no_hs), "total_amount")
        assert (amount2["status"] == "NOT_CHECKED"), ("两份都没币种 -> NOT_CHECKED", str(amount2))

    def test_rules_unverified_guard(self) -> None:
        from app.pipeline import rules

        assert (rules.ruleset_verified() is False), "当前规则集未核实（verified=false）"

        original = rules.load_rules
        try:
            rules.load_rules = lambda: {"version": "x", "verified": True, "verified_by": None}
            assert (rules.ruleset_verified() is False), "只把 verified 改成 true、不填核实人 -> 仍算未核实"
            rules.load_rules = lambda: {"version": "x", "verified": True, "verified_by": "C-某人"}
            assert (rules.ruleset_verified() is False), "核实日期缺失 -> 仍算未核实"
            rules.load_rules = lambda: {"version": "x", "verified": True, "verified_by": "C-某人", "verified_at": "2026-10-12"}
            assert (rules.ruleset_verified() is True), "verified=true 且核实人、日期完整 -> 才算已核实"
        finally:
            rules.load_rules = original

    def test_description_critical_token(self) -> None:
        base = "陶瓷 马克杯 350ML 食品级 加厚 出口 包装 白"
        other = "陶瓷 马克杯 350ML 食品级 加厚 出口 包装 红"
        # 先确认这种情形相似度确实高于阈值（否则测不出「闸门」的作用）
        from app.pipeline.compare import _similarity, _SIMILARITY_THRESHOLD

        sim = _similarity(base, other)
        assert (sim >= _SIMILARITY_THRESHOLD), (f"相似度 {sim:.3f} 高于阈值 {_SIMILARITY_THRESHOLD}（差异会被掩盖）", f"sim={sim}")
        cmp = _desc_comparison(base, other)
        assert (cmp["status"] == "CONFLICT"), ("颜色不同 -> CONFLICT", str(cmp))
        assert ("关键属性" in (cmp["note"] or "")), ("note 指出关键属性差异", str(cmp["note"]))

    def test_description_spec_digit(self) -> None:
        cmp = _desc_comparison(
            "陶瓷 马克杯 350ML 白 食品级 加厚 出口 包装",
            "陶瓷 马克杯 500ML 白 食品级 加厚 出口 包装",
        )
        assert (cmp["status"] == "CONFLICT"), ("容量 350ML vs 500ML -> CONFLICT", str(cmp))

    def test_description_fuzzy_ok(self) -> None:
        cmp = _desc_comparison("陶瓷 马克杯 350ML 白", "陶瓷 马克杯 350ML 白 釉")
        assert (cmp["status"] == "MATCH"), ("写法不同但同一件货 -> MATCH", str(cmp))

    def test_confidence_is_null(self) -> None:
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
        assert (len(extracted) >= 3), ("确实抽出了字段（否则测试没意义）", str(len(extracted)))
        assert (all(f["confidence"] is None for f in extracted)), ("所有已抽出字段的 confidence 均为 null", str([(f["field_key"], f["confidence"]) for f in extracted]))
        assert (all(f["confidence"] is None for f in fields)), ("未抽出字段的 confidence 也为 null", "存在非 null")

    def test_table_stripped(self) -> None:
        from app.pipeline.rows import parse_line_items

        t = parse_line_items(TABLE_TEXT)
        assert (len(t.line_items) == 2), ("认出 2 个品名行", str(len(t.line_items)))
        assert ("ITEM NO." not in t.doc_text), ("表头没残留进票级文本", t.doc_text)
        assert ("HM-1001" not in t.doc_text), ("品名行没残留进票级文本", t.doc_text)
        assert ("TOTAL PACKAGES: 100" in t.doc_text), ("合计行保留给票级", t.doc_text)

        fields = extract_fields(t.doc_text, "COMMERCIAL_INVOICE", page=1, row_keys=t.header_keys)
        by_key = {f["field_key"]: f for f in fields}
        assert (by_key["packages"]["normalized_value"] == 100), ("票级件数取到合计值 100", str(by_key["packages"]))
        # 剥掉之前，票级会把行号当总金额（实测踩过的 bug）
        assert (by_key["total_amount"]["normalized_value"] is None), ("票级总金额不再抓到行号", str(by_key["total_amount"]))
        assert (by_key["description"]["status"] == "NOT_IN_DOC"), ("按行提供的字段在票级报 NOT_IN_DOC（不是 MISSING）", str(by_key["description"]["status"]))

    def test_align_by_code_any_order(self) -> None:
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
        assert (len(items) == 2), ("对齐出 2 个行组", str(items))
        assert (all(i["alignment_status"] == "ALIGNED" for i in items)), ("全部 ALIGNED", str(items))
        assert (all(i["alignment_basis"] == "ITEM_CODE" for i in items)), ("依据是货号", str(items))

        mug = next(i for i in items if "马克杯" in i["label"])
        members = {(m["file_id"], m["item_no"]) for m in mug["members"]}
        assert (members == {("f1", 1), ("f2", 2)}), ("发票第 1 行对上了装箱单第 2 行", str(members))
        assert (all(m["match_score"] == 1.0 for m in mug["members"])), ("货号一致时 match_score=1.0", str(mug["members"]))

        cmps = build_item_comparisons(items, docs, exts, no_hs, "DE", "德国")
        pack = find(cmps, "packages")
        assert (pack is not None and pack["status"] == "MATCH"), ("品名级件数 60 vs 60 -> MATCH", str(pack))
        assert (pack["scope"] == "ITEM" and pack["item_id"]), ("品名级比对带 scope=ITEM 与 item_id", str(pack))
        conflicts = [c for c in cmps if c["status"] == "CONFLICT"]
        assert (len(conflicts) == 1 and conflicts[0]["field_key"] == "packages"), ("盘子件数 40 vs 45 -> CONFLICT", str(conflicts))
        assert (all(c["scope"] == "ITEM" for c in cmps)), ("票级比对不受影响（没有同名字段混入）", "存在非 ITEM 条目")

    def test_align_by_description(self) -> None:
        from app.pipeline.align import align_items

        docs = [doc("f1", "A.pdf"), doc("f2", "B.pdf"), doc("f3", "C.pdf")]
        exts = [
            rows_extraction("f1", [row(1, [field("description", "陶瓷 马克杯 350ML 白")])]),
            rows_extraction("f2", [row(1, [field("description", "陶瓷 马克杯 350ML 白")])]),
            rows_extraction("f3", [row(1, [field("description", "陶瓷 马克杯 350ML")])]),
        ]
        items = align_items(exts, docs)
        assert (len(items) == 1), ("三份文件合成 1 个行组", str(items))
        assert (items[0]["alignment_basis"] == "DESCRIPTION"), ("依据是描述", str(items[0]))
        assert (len(items[0]["members"]) == 3), ("三个成员都在同一组", str(items[0]["members"]))
        assert (items[0]["alignment_status"] == "ALIGNED"), ("状态为 ALIGNED", str(items[0]))
        assert (items[0]["alignment_note"] is None), ("ALIGNED 时 alignment_note 为 null", str(items[0]))

    def test_unresolved_never_concludes(self) -> None:
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
        assert (not [i for i in items if i["alignment_status"] == "ALIGNED"]), ("没有硬凑成 ALIGNED", str(items))
        assert (any(i["alignment_status"] == "UNALIGNED" for i in items)), ("确实有 UNALIGNED 行组", str(items))
        for i in items:
            if i["alignment_status"] in ("UNALIGNED", "PARTIAL"):
                assert (bool(i["alignment_note"])), (f"{i['item_id']} 对不上时必须给出原因", str(i))

        cmps = build_item_comparisons(items, docs, exts, no_hs, "DE", "德国")
        bad = [c for c in cmps if c["status"] in ("MATCH", "CONFLICT")]
        assert (not bad), ("对不上的行组不得产出 MATCH / CONFLICT", str(bad))
        unaligned_ids = {i["item_id"] for i in items if i["alignment_status"] == "UNALIGNED"}
        hit = [c for c in cmps if c["item_id"] in unaligned_ids]
        assert (bool(hit)), ("UNALIGNED 行组有产出比对条目（不是静默省略）", "没有条目")
        assert (all(c["status"] == "NOT_CHECKED" for c in hit)), ("UNALIGNED 行组一律 NOT_CHECKED", str(hit))
        assert (all(c["note"] for c in hit)), ("NOT_CHECKED 都带 note", str(hit))

    def test_partial_groups(self) -> None:
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
        assert (len(items) == 3), ("共 3 个行组（1 组对齐 + 2 组单边）", str(items))
        assert (len([i for i in items if i["alignment_status"] == "ALIGNED"]) == 1), ("对齐的那组是 ALIGNED", str(items))
        partials = [i for i in items if i["alignment_status"] == "PARTIAL"]
        assert (len(partials) == 2), ("两组单边的都是 PARTIAL", str(items))
        assert (all(len(i["members"]) == 1 for i in partials)), ("单边行组只有一个成员", str(partials))
        assert (sorted((m["file_id"], m["item_no"]) for i in items for m in i["members"])
            == [("f1", 1), ("f1", 2), ("f2", 1), ("f2", 2)]), ("每一行都出现在某个行组里（没有行被丢掉）", str(items))

    def test_row_field_not_applicable(self) -> None:
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
        assert (hs["status"] == "SINGLE_SOURCE"), ("HS 只在一份文件里适用 -> SINGLE_SOURCE", str(hs))
        assert (hs["status"] != "MISSING_IN_SOME"), ("不是 MISSING_IN_SOME（那会把正常差异报成缺失）", str(hs))
        assert ("发票" in (hs["note"] or "")), ("note 说明了是哪一份文件", str(hs["note"]))
        assert (len(hs["values"]) == 1), ("NOT_IN_DOC 的那份不进 values", str(hs["values"]))


if __name__ == "__main__":
    unittest.main()
