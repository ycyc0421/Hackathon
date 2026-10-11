"""生成「格式与语言不统一」挑战样例：同内容 PNG 图片 + 文本层 PDF。

和 make_samples.py 的区别：那三套是"格式工整"的基线；这里刻意制造
赛题背景里说的「单证格式与语言不统一」，用来验证后端归一化与比对的
真实成色 —— 每一处不一致都有明确的预期结果，见 samples/challenge/金标预期.md。

三套样例：
  09_us_format_mixed        值全一致、写法五花八门（中文发票/英文装箱单/英文提单），
                            日期三种写法、单位两种语言、HS 两种写法 => 归一后应 0 冲突
  10_de_ambiguity_conflict  格式陷阱（中文日期、US$ 币种、欧式小数、美式歧义日期）+ 1 个真冲突
  11_de_multiitem_mixed     多品名：行序打乱、描述中英混排（1 项跨语言应判同、1 项颜色真冲突）、提单仅汇总

用法：
  python tools/make_challenge_samples.py
"""

from __future__ import annotations

import random
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND_DIR / "samples"

FONT_CN = "C:/Windows/Fonts/Deng.ttf"       # 等线（含中文）
FONT_CN_B = "C:/Windows/Fonts/Dengb.ttf"
FONT_EN = "C:/Windows/Fonts/arial.ttf"
FONT_EN_B = "C:/Windows/Fonts/arialbd.ttf"
FONT_MONO = "C:/Windows/Fonts/cour.ttf"

SHIPPER = "NINGBO YATAI CERAMICS CO., LTD."


def grid(header: list[str], rows: list[list[str]]) -> list[str]:
    """定宽文本表格：列间 >=2 空格（行切分器靠这个判断列边界）。"""
    widths = []
    for i, name in enumerate(header):
        widest = max([len(str(name))] + [len(str(r[i])) for r in rows])
        widths.append(widest + 2)

    def fmt(cells: list[str]) -> str:
        return "".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    return [fmt(header)] + [fmt(r) for r in rows]


# ==========================================================================
# 08 · 美国 · 值全一致，格式与语言五花八门
# ==========================================================================
DOC_08_INVOICE = {
    "name": "商业发票-INVOICE2026-2001.pdf",
    "title": "商业发票  COMMERCIAL INVOICE",
    "lines": [
        "发货人：NINGBO YATAI CERAMICS CO., LTD.",
        "收货人：AMERICAN HOME GOODS INC.",
        "发票号：INV-2026-2001",
        "合同号：CT-2026-088",
        "装运日期：2026-10-08",
        "起运港：上海 SHANGHAI",
        "目的港：洛杉矶 LOS ANGELES",
        "目的国：美国 USA",
        "货物描述：CERAMIC TABLEWARE",
        "数量：9600 个（PCS）",
        "件数：120 箱（CARTONS）",
        "毛重：2,400.00 千克（KGS）",
        "净重：2,100.00 千克（KGS）",
        "海关编码：6911.10.00",
        "总金额：12,500.00 美元（USD）",
    ],
}

DOC_08_PACKING = {
    "name": "Packing-List-PL2026-2001.pdf",
    "title": "PACKING LIST",
    "lines": [
        f"SHIPPER: {SHIPPER}",
        "CONSIGNEE: AMERICAN HOME GOODS INC.",
        "INVOICE NO.: INV-2026-2001",
        "SHIPMENT DATE: 08.10.2026",
        "NO. OF PACKAGES: 120 CTNS",
        "G.W.: 2,400.00 KGS",
        "N.W.: 2,100.00 KGS",
        "MEAS.: 28.80 CBM",
        "DESCRIPTION: CERAMIC TABLEWARE",
        "QTY: 9600 PCS",
        "PORT OF LOADING: SHANGHAI, CHINA",
        "PORT OF DISCHARGE: LOS ANGELES, USA",
    ],
}

DOC_08_BL = {
    "name": "Bill-of-Lading-BL2026-2001.pdf",
    "title": "BILL OF LADING",
    "lines": [
        f"SHIPPER: {SHIPPER}",
        "CONSIGNEE: AMERICAN HOME GOODS INC.",
        "B/L NO.: BLUS-2026-2001",
        "PORT OF LOADING: SHANGHAI, CHINA",
        "PORT OF DISCHARGE: LOS ANGELES, USA",
        "CONTAINER NO.: TCLU1234567",
        "SHIPPED ON BOARD: OCT 8, 2026",
        "DESCRIPTION OF GOODS: CERAMIC TABLEWARE",
        "SAY ONE HUNDRED AND TWENTY (120) CARTONS ONLY",
        "G.W.: 2,400.00 KGS",
        "N.W.: 2,100.00 KGS",
        "HS CODE: 6911100000",
    ],
}

# ==========================================================================
# 09 · 德国 · 格式陷阱 + 真冲突（数量 9800 vs 9600）
# ==========================================================================
DOC_09_INVOICE = {
    "name": "商业发票-INVOICE2026-3001.pdf",
    "title": "商业发票  COMMERCIAL INVOICE",
    "lines": [
        f"发货人：{SHIPPER}",
        "收货人：MUELLER HAUSWARE GMBH",
        "发票号：INV-2026-3001",
        "装运日期：2026年10月05日",  # 陷阱A：中文日期
        "起运港：上海 SHANGHAI",
        "目的港：汉堡 HAMBURG",
        "货物描述：CERAMIC TABLEWARE",
        "数量：9800 个（PCS）",  # 真冲突：装箱单 9600
        "件数：120 箱（CARTONS）",
        "毛重：2,400.00 千克（KGS）",
        "海关编码：6911.10",
        "总金额：US$12,500.00",  # 陷阱B：US$ 币种
    ],
}

DOC_09_PACKING = {
    "name": "Packing-List-PL2026-3001.pdf",
    "title": "PACKING LIST",
    "lines": [
        f"SHIPPER: {SHIPPER}",
        "CONSIGNEE: MUELLER HAUSWARE GMBH",
        "INVOICE NO.: INV-2026-3001",
        "SHIPMENT DATE: 10/05/2026",  # 陷阱C：两种地区格式都成立，不得猜
        "NO. OF PACKAGES: 120 CTNS",
        "G.W.: 2.400,00 KGS",  # 陷阱D：欧式小数
        "N.W.: 2.100,00 KGS",
        "QTY: 9600 PCS",
        "DESCRIPTION: CERAMIC TABLEWARE",
        "PORT OF LOADING: SHANGHAI, CHINA",
        "PORT OF DISCHARGE: HAMBURG, GERMANY",
    ],
    "scan": True,  # 这张图按"扫描件"处理：倾斜 + 噪点
}

DOC_09_BL = {
    "name": "Bill-of-Lading-BL2026-3001.pdf",
    "title": "BILL OF LADING",
    "lines": [
        f"SHIPPER: {SHIPPER}",
        "CONSIGNEE: MUELLER HAUSWARE GMBH",
        "B/L NO.: BLDE-2026-3001",
        "PORT OF LOADING: SHANGHAI, CHINA",
        "PORT OF DISCHARGE: HAMBURG, GERMANY",
        "SHIPPED ON BOARD: OCT 5, 2026",
        "DESCRIPTION OF GOODS: CERAMIC TABLEWARE",
        "SAY ONE HUNDRED AND TWENTY (120) CARTONS ONLY",
        "G.W.: 2,400.00 KGS",
        "INVOICE VALUE: 12,500.00 EUR",  # 陷阱E：币种 EUR
        "HS CODE: 6911.10.00",
    ],
}

# ==========================================================================
# 10 · 德国 · 多品名：行序打乱 + 描述中英混排 + 颜色真冲突
# ==========================================================================
INV_HEADER_10 = ["NO.", "ITEM NO.", "DESCRIPTION", "HS CODE", "QTY", "PACKAGES", "G.W.", "AMOUNT"]
PACK_HEADER_10 = ["NO.", "ITEM NO.", "DESCRIPTION", "QTY", "PACKAGES", "G.W."]

# (货号, 发票描述, HS, 数量, 件数, 毛重, 金额)
ITEMS_10 = [
    ("YT-M001", "CERAMIC MUG 350ML WHITE", "6911.10.00", "2400 PCS", "30 CTNS", "600.00", "3,600.00"),
    ("YT-M002", "陶瓷 餐具 16PC 蓝", "6911.10.00", "1800 PCS", "40 CTNS", "900.00", "4,500.00"),
    ("YT-M003", "PORCELAIN PLATE 8INCH", "6912.00.00", "3000 PCS", "30 CTNS", "750.00", "3,000.00"),
    ("YT-M004", "CERAMIC BOWL 4.5INCH BEIGE", "6912.00.00", "2400 PCS", "20 CTNS", "550.00", "2,400.00"),
]

# 装箱单：行序打乱（3,1,4,2）；M004 颜色写 BLUE（发票写 BEIGE => 真冲突）；
# M002 描述写成英文（发票是中文 => 跨语言应判同）
PACK_ROWS_10 = [
    ["1", "YT-M003", "PORCELAIN PLATE 8INCH", "3000 PCS", "30 CTNS", "750.00"],
    ["2", "YT-M001", "CERAMIC MUG 350ML WHITE", "2400 PCS", "30 CTNS", "600.00"],
    ["3", "YT-M004", "CERAMIC BOWL 4.5INCH BLUE", "2400 PCS", "20 CTNS", "550.00"],
    ["4", "YT-M002", "CERAMIC TABLEWARE 16PC BLUE", "1800 PCS", "40 CTNS", "900.00"],
]

DOC_10_INVOICE = {
    "name": "商业发票-INVOICE2026-4001.pdf",
    "title": "商业发票  COMMERCIAL INVOICE",
    "lines": [
        f"发货人：{SHIPPER}",
        "收货人：MUELLER HAUSWARE GMBH",
        "发票号：INV-2026-4001",
        "装运日期：2026-10-08",
        "起运港：上海 SHANGHAI",
        "目的港：汉堡 HAMBURG",
    ],
    "table": grid(
        INV_HEADER_10,
        [
            [str(i + 1), it[0], it[1], it[2], it[3], it[4], it[5], it[6]]
            for i, it in enumerate(ITEMS_10)
        ],
    ),
    "after_table": [
        "合计/TOTAL: 9600 PCS  120 CARTONS  G.W. 2,800.00 KGS  AMOUNT USD 13,500.00",
    ],
}

DOC_10_PACKING = {
    "name": "Packing-List-PL2026-4001.pdf",
    "title": "PACKING LIST",
    "lines": [
        f"SHIPPER: {SHIPPER}",
        "CONSIGNEE: MUELLER HAUSWARE GMBH",
        "INVOICE NO.: INV-2026-4001",
        "ISSUE DATE: 08.10.2026",
        "PORT OF LOADING: SHANGHAI, CHINA",
        "PORT OF DISCHARGE: HAMBURG, GERMANY",
    ],
    "table": grid(PACK_HEADER_10, PACK_ROWS_10),
    "after_table": [
        "TOTAL PACKAGES: 120 CTNS",
        "TOTAL G.W.: 2,800.00 KGS",
    ],
}

DOC_10_BL = {
    "name": "Bill-of-Lading-BL2026-4001.pdf",
    "title": "BILL OF LADING",
    "lines": [
        f"SHIPPER: {SHIPPER}",
        "CONSIGNEE: MUELLER HAUSWARE GMBH",
        "B/L NO.: BLDE-2026-4001",
        "PORT OF LOADING: SHANGHAI, CHINA",
        "PORT OF DISCHARGE: HAMBURG, GERMANY",
        "SHIPPED ON BOARD: OCT 8, 2026",
        "DESCRIPTION OF GOODS: CERAMIC TABLEWARE (DETAILS AS PER INVOICE)",
        "SAY ONE HUNDRED AND TWENTY (120) CARTONS ONLY",
        "G.W.: 2,800.00 KGS",
        "HS CODE: 6911.10.00",
    ],
}

CASES = [
    ("09_us_format_mixed", "US", "美国", [DOC_08_INVOICE, DOC_08_PACKING, DOC_08_BL]),
    ("10_de_ambiguity_conflict", "DE", "德国", [DOC_09_INVOICE, DOC_09_PACKING, DOC_09_BL]),
    ("11_de_multiitem_mixed", "DE", "德国", [DOC_10_INVOICE, DOC_10_PACKING, DOC_10_BL]),
]


# ==========================================================================
# 渲染：PDF（文本层，后端今天就能处理）
# ==========================================================================
def render_pdf(path: Path, doc: dict) -> None:
    from fpdf import FPDF

    has_table = "table" in doc
    size = 8 if has_table else 10
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("cn", "", FONT_CN)
    pdf.add_font("cnb", "", FONT_CN_B)

    # 标题
    pdf.set_font("cnb", size=size + 4)
    pdf.cell(0, 7, doc["title"], align="c", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_draw_color(120, 120, 120)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)

    pdf.set_font("cn", size=size)
    for line in doc.get("lines", []):
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    if has_table:
        pdf.ln(2)
        for line in doc["table"]:
            pdf.cell(0, 4.6, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        for line in doc.get("after_table", []):
            pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


# ==========================================================================
# 渲染：PNG（图片，多模态/OCR 通道用；09 装箱单做扫描件效果）
# ==========================================================================
PAGE_W, PAGE_H = 1240, 1754  # A4 @150dpi


def _is_cjk(text: str) -> bool:
    return any(ord(c) > 0x2E7F for c in text)


def render_png(path: Path, doc: dict) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (PAGE_W, PAGE_H), (252, 251, 248))  # 纸感底色
    draw = ImageDraw.Draw(img)
    margin = 90
    y = 110

    f_title = ImageFont.truetype(FONT_CN_B, 40)
    f_body_cn = ImageFont.truetype(FONT_CN, 27)
    f_body_en = ImageFont.truetype(FONT_EN, 27)
    f_tab = ImageFont.truetype(FONT_MONO, 20)
    f_tab_cn = ImageFont.truetype(FONT_CN, 20)

    # 标题居中 + 分隔线
    w = draw.textlength(doc["title"], font=f_title)
    draw.text(((PAGE_W - w) / 2, y), doc["title"], fill=(20, 20, 20), font=f_title)
    y += 64
    draw.line([(margin, y), (PAGE_W - margin, y)], fill=(90, 90, 90), width=3)
    y += 40

    def draw_line(text: str, font, fill=(25, 25, 25)) -> None:
        nonlocal y
        draw.text((margin, y), text, fill=fill, font=font)
        y += int(font.size * 1.55)

    for line in doc.get("lines", []):
        draw_line(line, f_body_cn if _is_cjk(line) else f_body_en)

    if "table" in doc:
        y += 16
        # 列起点按「整列最宽单元格 + 2 间距」计算（与 grid() 的定宽逻辑一致），
        # courier 等宽字符宽 × 字符数 = 列宽，数据再长也不会叠进下一列
        table = doc["table"]
        header_cells = _split_row(table[0])
        rows_cells = [_split_row(r) for r in table[1:]]
        ncol = len(header_cells)
        unit = draw.textlength("0", font=f_tab)
        widths = []
        for i in range(ncol):
            lens = [len(header_cells[i])] + [len(r[i]) for r in rows_cells if i < len(r)]
            widths.append(max(lens) + 2)
        col_x = [margin]
        for wdt in widths[:-1]:
            col_x.append(col_x[-1] + wdt * unit)
        for i, row_line in enumerate(table):
            cells = _split_row(row_line)
            font = f_tab if not _is_cjk(row_line) else f_tab_cn
            fill = (70, 70, 70) if i == 0 else (25, 25, 25)
            for j, cell in enumerate(cells):
                if j < len(col_x):
                    draw.text((col_x[j], y), cell, fill=fill, font=font)
            y += 36
        y += 16
        for line in doc.get("after_table", []):
            draw_line(line, f_body_cn if _is_cjk(line) else f_body_en)

    # 页脚
    draw.text((margin, PAGE_H - 70), "Page 1 of 1", fill=(120, 120, 120), font=f_body_en)

    if doc.get("scan"):
        img = _scan_effect(img)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path), "PNG")


def _split_row(line: str) -> list[str]:
    """把定宽行拆回单元格（>=2 空格为列边界），用于 PNG 按列绘制。"""
    import re

    return [c for c in re.split(r"\s{2,}", line.strip()) if c]


def _scan_effect(img):
    """模拟扫描件：轻微倾斜 + 噪点 + 纸张发灰。"""
    from PIL import Image, ImageFilter  # noqa: F401  Image 供 BICUBIC 常量使用

    random.seed(2026)
    img = img.rotate(1.4, resample=Image.BICUBIC, fillcolor=(238, 235, 228))
    px = img.load()
    w, h = img.size
    for _ in range(26000):
        x, yy = random.randrange(w), random.randrange(h)
        v = random.randint(150, 215)
        px[x, yy] = (v, v, v - random.randint(0, 12))
    return img.filter(ImageFilter.GaussianBlur(0.4))


def main() -> None:
    for dir_name, _cc, _cn, docs in CASES:
        d = SAMPLES_DIR / dir_name
        for doc in docs:
            render_pdf(d / doc["name"], doc)
            png_name = Path(doc["name"]).stem + ".png"
            render_png(d / png_name, doc)
            print(f"  {dir_name}/{doc['name']}  +  {png_name}")
    print(f"挑战样例已生成：{SAMPLES_DIR}")


if __name__ == "__main__":
    main()
