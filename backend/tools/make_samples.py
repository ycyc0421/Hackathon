"""生成三套示例单证，用于 W1 的「解析 → 比对」跑通与联调演示。

    python tools/make_samples.py

产物在 backend/samples/ 下：

  01_us_consistent/  三份单证互相一致         -> COMPLETED，无冲突，HS 命中规则
  02_de_conflict/    件数与毛重对不上         -> COMPLETED，2 处 CONFLICT
  03_de_partial/     含一份无法识别的图片     -> PARTIAL，覆盖 6 种异常状态

真实单证由 C 的单证生成器产出；这里先用自造样例把链路跑通，
对应契约第四节第 5 项「成套单证样例的提供时间尚未确定」。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


def write_pdf(path: Path, lines: list[str], size: int = 10) -> None:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=size)
    for line in lines:
        if line == "":
            pdf.ln(4)
            continue
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


def grid(header: list[str], rows: list[list[str]]) -> list[str]:
    """把表头与数据行排成定宽文本行。

    列间至少留 2 个空格 —— 行切分器就是靠「≥2 个空格」判断列边界的，
    单空格会被当成描述内部的分词。
    """
    widths = []
    for i, name in enumerate(header):
        widest = max([len(str(name))] + [len(str(r[i])) for r in rows])
        widths.append(widest + 2)

    def fmt(cells: list[str]) -> str:
        return "".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    return [fmt(header)] + [fmt(r) for r in rows]


def write_png(path: Path, width: int = 40, height: int = 20) -> None:
    """写一张极小的 PNG —— 用来演示「图像分辨率过低，无法识别版式」。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


# --------------------------------------------------------------------------
# 01 · 三份单证互相一致（目的国美国）
# --------------------------------------------------------------------------
def sample_us_consistent() -> None:
    d = SAMPLES_DIR / "01_us_consistent"

    write_pdf(
        d / "商业发票-INV20261012.pdf",
        [
            "COMMERCIAL INVOICE",
            "INVOICE NO.: INV-2026-1012",
            "DATE OF ISSUE: 2026-10-08",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: PACIFIC HOME GOODS INC.",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: LOS ANGELES, USA",
            "COUNTRY OF DESTINATION: UNITED STATES",
            "",
            "DESCRIPTION OF GOODS: CERAMIC MUG 350ML WHITE",
            "HS CODE: 6911.10.00",
            "QUANTITY: 2400 PCS",
            "PACKAGES: 120 CARTONS",
            "G.W.: 2,400.00 KGS",
            "N.W.: 2,100.00 KGS",
            "",
            "TOTAL: USD 12,500.00",
        ],
    )

    write_pdf(
        d / "装箱单-PL20261012.pdf",
        [
            "PACKING LIST",
            "INVOICE NO.: INV-2026-1012",
            "DATE OF ISSUE: 2026-10-08",
            "",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: LOS ANGELES, USA",
            "",
            "DESCRIPTION OF GOODS: CERAMIC MUG, 350ML, WHITE GLAZE",
            "QUANTITY: 2400 PCS",
            "PACKAGES: 120 CARTONS",
            "G.W.: 2,400.00 KGS",
            "N.W.: 2,100.00 KGS",
            "MEAS.: 12.500 CBM",
        ],
    )

    write_pdf(
        d / "提单-BL20261012.pdf",
        [
            "BILL OF LADING",
            "B/L NO.: MAEU2610123456",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: PACIFIC HOME GOODS INC.",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: LOS ANGELES, USA",
            "SHIPPED ON BOARD 08 OCT 2026",
            "",
            "DESCRIPTION OF GOODS: CERAMIC MUG 350ML WHITE",
            "PACKAGES: 120 CARTONS",
            "G.W.: 2400.00 KGS",
            "MEAS.: 12.500 CBM",
        ],
    )


# --------------------------------------------------------------------------
# 02 · 件数与毛重对不上（目的国德国）
# --------------------------------------------------------------------------
def sample_de_conflict() -> None:
    d = SAMPLES_DIR / "02_de_conflict"

    write_pdf(
        d / "商业发票-INV20261013.pdf",
        [
            "COMMERCIAL INVOICE",
            "INVOICE NO.: INV-2026-1013",
            "DATE OF ISSUE: 2026-10-09",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "COUNTRY OF DESTINATION: GERMANY",
            "",
            "DESCRIPTION OF GOODS: CERAMIC MUG 350ML WHITE",
            "HS CODE: 6911.10.00",
            "QUANTITY: 2400 PCS",
            "PACKAGES: 100 CARTONS",
            "G.W.: 2,400.00 KGS",
            "N.W.: 2,100.00 KGS",
            "",
            "TOTAL: USD 12,500.00",
        ],
    )

    write_pdf(
        d / "装箱单-PL20261013.pdf",
        [
            "PACKING LIST",
            "INVOICE NO.: INV-2026-1013",
            "DATE OF ISSUE: 2026-10-09",
            "",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "",
            "DESCRIPTION OF GOODS: CERAMIC MUG, 350ML, WHITE GLAZE",
            "QUANTITY: 2400 PCS",
            "PACKAGES: 120 CARTONS",
            "G.W.: 2,500.00 KGS",
            "N.W.: 2,100.00 KGS",
            "MEAS.: 12.500 CBM",
        ],
    )

    write_pdf(
        d / "提单-BL20261013.pdf",
        [
            "BILL OF LADING",
            "B/L NO.: MAEU2610139876",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "SHIPPED ON BOARD 09 OCT 2026",
            "",
            "DESCRIPTION OF GOODS: CERAMIC MUG 350ML WHITE",
            "PACKAGES: 120 CARTONS",
            "G.W.: 2400.00 KGS",
            "MEAS.: 12.500 CBM",
        ],
    )


# --------------------------------------------------------------------------
# 03 · 含无法识别的图片，覆盖六种异常状态（目的国德国）
# --------------------------------------------------------------------------
def sample_de_partial() -> None:
    d = SAMPLES_DIR / "03_de_partial"

    write_pdf(
        d / "商业发票-INV20261014.pdf",
        [
            "COMMERCIAL INVOICE",
            "INVOICE NO.: INV-2026-1014",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "COUNTRY OF DESTINATION: GERMANY",
            "",
            "DESCRIPTION OF GOODS: CERAMIC MUG 350ML WHITE",
            "HS CODE: 6911.10.00",
            "QUANTITY: 2400 PCS",
            "PACKAGES: 120 CARTONS",
            # 定位得到标签但读不出值 -> UNRECOGNIZED
            "G.W. *********",
            # 发票按规则应有净重却没有 -> MISSING_IN_DOC
            "",
            "TOTAL: USD 12,500.00",
        ],
    )

    write_pdf(
        d / "装箱单-PL20261014.pdf",
        [
            "PACKING LIST",
            "INVOICE NO.: INV-2026-1014",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "",
            "DESCRIPTION OF GOODS: CERAMIC MUG, 350ML, WHITE GLAZE",
            "QUANTITY: 2400 PCS",
            "PACKAGES: 120 CARTONS",
            "G.W.: 2,400.00 KGS",
            "N.W.: 2,100.00 KGS",
            # 读出值了但无法归一 -> NORMALIZE_FAILED
            "MEAS.: UNKNOWN",
        ],
    )

    # 低分辨率扫描件 —— 未配置多模态兜底时显式失败，任务整体转为 PARTIAL
    write_png(d / "提单-扫描件.png", width=40, height=20)


# --------------------------------------------------------------------------
# 多品名样例（v0.2）：一票货含多个品名
# --------------------------------------------------------------------------
INV_HEADER = ["NO.", "ITEM NO.", "DESCRIPTION", "HS CODE", "QTY", "PACKAGES", "N.W.", "G.W.", "AMOUNT"]
PACK_LITE = ["NO.", "ITEM NO.", "DESCRIPTION", "QTY", "PACKAGES", "N.W.", "G.W.", "MEAS."]
PACK_NO_CODE = ["NO.", "DESCRIPTION", "QTY", "PACKAGES", "N.W.", "G.W."]
INV_NO_CODE = ["NO.", "DESCRIPTION", "QTY", "PACKAGES", "G.W."]

# (货号, 描述, HS, 数量, 件数, 净重, 毛重, 金额, 体积)
ITEMS_04 = [
    ("HM-1001", "CERAMIC MUG 350ML WHITE", "6911.10.00", "1200 PCS", "60 CARTONS", "1050.00 KGS", "1200.00 KGS", "6240.00", "4.200 CBM"),
    ("HM-1002", "CERAMIC PLATE 20CM BLUE", "6912.00.00", "800 PCS", "40 CARTONS", "840.00 KGS", "960.00 KGS", "3280.00", "3.100 CBM"),
    ("HM-1003", "CERAMIC BOWL 15CM GREEN", "6912.00.00", "600 PCS", "30 CARTONS", "630.00 KGS", "720.00 KGS", "1980.00", "2.400 CBM"),
    ("HM-1004", "CERAMIC TEAPOT 1.0L WHITE", "6911.10.00", "200 PCS", "10 CARTONS", "250.00 KGS", "300.00 KGS", "1700.00", "1.300 CBM"),
]


def _inv_rows(items) -> list[list[str]]:
    return [
        [str(i + 1), code, desc, hs, qty, pkg, nw, gw, amt]
        for i, (code, desc, hs, qty, pkg, nw, gw, amt, _) in enumerate(items)
    ]


def _pack_rows(items, order: list[int] | None = None) -> list[list[str]]:
    """装箱单行。order 用于把行序打乱 —— 刻意让两份文件的顺序不同，
    因为「同一个品名在两份文件里行号不同」是多品名最常见的真实情形。"""
    idx = order if order is not None else list(range(len(items)))
    out = []
    for n, k in enumerate(idx, start=1):
        code, desc, _, qty, pkg, nw, gw, _, meas = items[k]
        out.append([str(n), code, desc, qty, pkg, nw, gw, meas])
    return out


def sample_de_multiitem() -> None:
    """04 · 四个品名，文件间一致（目的国德国）。"""
    d = SAMPLES_DIR / "04_de_multiitem"

    write_pdf(
        d / "商业发票-INV20261015.pdf",
        [
            "COMMERCIAL INVOICE",
            "INVOICE NO.: INV-2026-1015",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "COUNTRY OF DESTINATION: GERMANY",
            "",
            *grid(INV_HEADER, _inv_rows(ITEMS_04)),
            "",
            "TOTAL PACKAGES: 140 CARTONS",
            "TOTAL G.W.: 3,180.00 KGS",
            "TOTAL: USD 13,200.00",
        ],
        size=8,
    )

    write_pdf(
        d / "装箱单-PL20261015.pdf",
        [
            "PACKING LIST",
            "INVOICE NO.: INV-2026-1015",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "",
            *grid(PACK_LITE, _pack_rows(ITEMS_04)),
            "",
            "TOTAL PACKAGES: 140 CARTONS",
            "TOTAL G.W.: 3,180.00 KGS",
        ],
        size=8,
    )

    # 提单只给整票汇总，没有品名明细 —— 这是常态，不是异常
    write_pdf(
        d / "提单-BL20261015.pdf",
        [
            "BILL OF LADING",
            "B/L NO.: MAEU2610150001",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "SHIPPED ON BOARD 10 OCT 2026",
            "",
            "DESCRIPTION OF GOODS: CERAMIC TABLEWARE, MIXED",
            "PACKAGES: 140 CARTONS",
            "G.W.: 3180.00 KGS",
            "MEAS.: 11.000 CBM",
        ],
        size=8,
    )


def sample_de_multiitem_conflict() -> None:
    """05 · 行序不同 + 同一品名多处冲突（目的国德国）。

    刻意造了四种冲突，每种考验比对引擎的不同能力：
      - 行序不同        -> 必须靠货号对齐，不能靠位置
      - 颜色词不同      -> 相似度很高，靠「关键属性闸门」才抓得住
      - 件数/金额不同    -> 数值比对
      - HS 编码不同     -> 编码比对
    """
    d = SAMPLES_DIR / "05_de_multiitem_conflict"

    pack_items = list(ITEMS_04)
    # 1002 的颜色改了（BLUE -> BEIGE）
    code, desc, hs, qty, pkg, nw, gw, amt, meas = pack_items[1]
    pack_items[1] = (code, "CERAMIC PLATE 20CM BEIGE", hs, qty, pkg, nw, gw, amt, meas)
    # 1003 的件数与金额改了
    code, desc, hs, qty, pkg, nw, gw, amt, meas = pack_items[2]
    pack_items[2] = (code, desc, hs, qty, "35 CARTONS", nw, gw, "2310.00", meas)
    # 1004 的 HS 编码改了
    code, desc, hs, qty, pkg, nw, gw, amt, meas = pack_items[3]
    pack_items[3] = (code, desc, "6913.00.00", qty, pkg, nw, gw, amt, meas)

    # 装箱单带 HS 与金额列（报关用），且行序被打乱：3、1、4、2
    pack_rows = [
        [str(n), it[0], it[1], it[2], it[3], it[4], it[5], it[6], it[7]]
        for n, it in enumerate([pack_items[2], pack_items[0], pack_items[3], pack_items[1]], start=1)
    ]

    write_pdf(
        d / "商业发票-INV20261016.pdf",
        [
            "COMMERCIAL INVOICE",
            "INVOICE NO.: INV-2026-1016",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "COUNTRY OF DESTINATION: GERMANY",
            "",
            *grid(INV_HEADER, _inv_rows(ITEMS_04)),
            "",
            "TOTAL PACKAGES: 140 CARTONS",
            "TOTAL G.W.: 3,180.00 KGS",
            "TOTAL: USD 13,200.00",
        ],
        size=8,
    )

    write_pdf(
        d / "装箱单-PL20261016.pdf",
        [
            "PACKING LIST",
            "INVOICE NO.: INV-2026-1016",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "",
            *grid(INV_HEADER, pack_rows),
            "",
            "TOTAL PACKAGES: 145 CARTONS",
            "TOTAL G.W.: 3,180.00 KGS",
            "TOTAL: USD 13,530.00",
        ],
        size=8,
    )


def sample_de_multiitem_gap() -> None:
    """06 · 一边少一行、一边多一行（目的国德国）。"""
    d = SAMPLES_DIR / "06_de_multiitem_gap"

    # 装箱单缺 HM-1004、多出一个 HM-1005
    pack_items = [ITEMS_04[0], ITEMS_04[1], ITEMS_04[2], ("HM-1005", "CERAMIC SAUCER 12CM WHITE", "6911.10.00", "300 PCS", "15 CARTONS", "180.00 KGS", "220.00 KGS", "960.00", "0.900 CBM")]

    write_pdf(
        d / "商业发票-INV20261017.pdf",
        [
            "COMMERCIAL INVOICE",
            "INVOICE NO.: INV-2026-1017",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "COUNTRY OF DESTINATION: GERMANY",
            "",
            *grid(INV_HEADER, _inv_rows(ITEMS_04)),
            "",
            "TOTAL PACKAGES: 140 CARTONS",
            "TOTAL G.W.: 3,180.00 KGS",
            "TOTAL: USD 13,200.00",
        ],
        size=8,
    )

    write_pdf(
        d / "装箱单-PL20261017.pdf",
        [
            "PACKING LIST",
            "INVOICE NO.: INV-2026-1017",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "",
            *grid(PACK_LITE, _pack_rows(pack_items)),
            "",
            "TOTAL PACKAGES: 145 CARTONS",
            "TOTAL G.W.: 3,400.00 KGS",
        ],
        size=8,
    )

    write_pdf(
        d / "提单-BL20261017.pdf",
        [
            "BILL OF LADING",
            "B/L NO.: MAEU2610170001",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "SHIPPED ON BOARD 10 OCT 2026",
            "",
            "DESCRIPTION OF GOODS: CERAMIC TABLEWARE, MIXED",
            "PACKAGES: 145 CARTONS",
            "G.W.: 3400.00 KGS",
        ],
        size=8,
    )


def sample_de_multiitem_unaligned() -> None:
    """07 · 两边都有品名行，但既无货号、描述也对不上（目的国德国）。

    这是最危险的情形：如果强行按行序配对，会报出两个看起来很正常的
    CONFLICT。正确做法是判 UNALIGNED —— 说白了就是「我看不出来哪行对哪行」，
    只能给 NOT_CHECKED，让人工来核。
    """
    d = SAMPLES_DIR / "07_de_multiitem_unaligned"

    inv_rows = [
        ["1", "CERAMIC MUG 350ML WHITE", "1200 PCS", "60 CARTONS", "1200.00 KGS"],
        ["2", "CERAMIC BOWL 15CM GREEN", "600 PCS", "30 CARTONS", "720.00 KGS"],
    ]
    pack_rows = [
        ["1", "PORCELAIN CUP 350ML", "1200 PCS", "60 CARTONS", "1050.00 KGS", "1200.00 KGS"],
        ["2", "PORCELAIN DISH 15CM", "600 PCS", "30 CARTONS", "630.00 KGS", "720.00 KGS"],
    ]

    write_pdf(
        d / "商业发票-INV20261018.pdf",
        [
            "COMMERCIAL INVOICE",
            "INVOICE NO.: INV-2026-1018",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "SHIPPER: NINGBO HOME CERAMICS CO., LTD.",
            "CONSIGNEE: HANSEATIC TRADING GMBH",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "COUNTRY OF DESTINATION: GERMANY",
            "",
            *grid(INV_NO_CODE, inv_rows),
            "",
            "TOTAL PACKAGES: 90 CARTONS",
            "TOTAL: USD 8,220.00",
        ],
        size=8,
    )

    write_pdf(
        d / "装箱单-PL20261018.pdf",
        [
            "PACKING LIST",
            "INVOICE NO.: INV-2026-1018",
            "DATE OF ISSUE: 2026-10-10",
            "",
            "PORT OF LOADING: NINGBO, CHINA",
            "PORT OF DISCHARGE: HAMBURG, GERMANY",
            "",
            *grid(PACK_NO_CODE, pack_rows),
            "",
            "TOTAL PACKAGES: 90 CARTONS",
        ],
        size=8,
    )


def main() -> None:
    sample_us_consistent()
    sample_de_conflict()
    sample_de_partial()
    sample_de_multiitem()
    sample_de_multiitem_conflict()
    sample_de_multiitem_gap()
    sample_de_multiitem_unaligned()
    from make_bilingual_sample import FONT, main as make_bilingual
    if FONT.exists():
        make_bilingual()
    print(f"示例单证已生成：{SAMPLES_DIR}")
    for sub in sorted(SAMPLES_DIR.iterdir()):
        if sub.is_dir():
            files = ", ".join(sorted(p.name for p in sub.iterdir()))
            print(f"  {sub.name}/  {files}")


if __name__ == "__main__":
    main()
