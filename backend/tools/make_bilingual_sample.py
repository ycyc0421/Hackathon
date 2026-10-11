"""生成一票四品名的中英双语、不同数字格式联调样例。"""

from pathlib import Path
from fpdf import FPDF
from make_samples import ITEMS_04, INV_HEADER, _inv_rows, grid, write_pdf

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "samples" / "08_de_bilingual_format"
FONT = Path(r"C:\Windows\Fonts\msyh.ttc")


def main() -> None:
    if not FONT.exists():
        raise SystemExit(f"缺少中文字体：{FONT}")
    DEST.mkdir(parents=True, exist_ok=True)
    write_pdf(
        DEST / "商业发票-INV20261015.pdf",
        [
            "COMMERCIAL INVOICE", "INVOICE NO.: INV-2026-1015",
            "SHIPMENT DATE: 2026-10-10", "",
            "PORT OF LOADING: NINGBO, CHINA", "PORT OF DISCHARGE: HAMBURG, GERMANY", "",
            *grid(INV_HEADER, _inv_rows(ITEMS_04)), "",
            "TOTAL PACKAGES: 140 CARTONS", "TOTAL G.W.: 3,180.00 KGS",
            "TOTAL: USD 13,200.00",
        ],
        size=8,
    )

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("SimSun", fname=str(FONT))
    pdf.set_font("SimSun", size=9)
    lines = [
        "装箱单 PACKING LIST",
        "发票号: INV-2026-1015",
        "装运日期: 2026/10/10",
        "起运港: 宁波", "目的港: 汉堡", "",
        "NO.  ITEM NO.  品名                         数量       件数      净重         毛重         体积",
        "1    HM-1001   陶瓷 马克杯 350ML 白           1200 个    60 箱     1050 公斤    1200 公斤    4.200 CBM",
        "2    HM-1002   陶瓷 盘 20CM 蓝             800 个     40 箱     840 公斤     960 公斤     3.100 CBM",
        "3    HM-1003   陶瓷 碗 15CM 绿             600 个     30 箱     630 公斤     720 公斤     2.400 CBM",
        "4    HM-1004   陶瓷 TEAPOT 1.0L 白        200 个     10 箱     250 公斤     300 公斤     1.300 CBM",
        "", "总件数: 140 箱", "毛重: 3180 公斤",
    ]
    for line in lines:
        if not line:
            pdf.ln(4)
        else:
            pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(DEST / "中文装箱单-PL20261015.pdf"))
    print(DEST)


if __name__ == "__main__":
    main()
