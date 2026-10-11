"""OCR table adapter guards; runs without downloading Paddle models."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.paddle_reader import (  # noqa: E402
    _check_descriptions,
    _sequential_packing_table,
    _table_lines,
)


def main() -> None:
    html = "<table><tr><td>NO.</td><td>ITEM NO.</td><td>DESCRIPTION</td><td></td><td>QTY</td></tr><tr><td>1</td><td>YT-M001</td><td>陶瓷餐具16PC蓝</td><td></td><td>1800 PCS</td></tr></table>"
    rows = _table_lines(html)
    assert rows == ["NO.   ITEM NO.   DESCRIPTION   QTY", "1   YT-M001   陶瓷餐具16PC蓝   1800 PCS"]
    try:
        _table_lines(html.replace('<td></td>', '<td colspan="2"></td>'))
    except ValueError:
        pass
    else:
        raise AssertionError("Merged table cell was accepted")
    merged, uncertain = _check_descriptions(rows, ["YT-M001", "陶瓷餐具 16PC 蓝"])
    assert merged[1] == "1   YT-M001   陶瓷餐具 16PC 蓝   1800 PCS"
    assert uncertain == []

    _, uncertain = _check_descriptions(rows, ["YT-M001", "CERAMIC TABLEWARE 16PC BLUE"])
    assert uncertain == ["YT-M001"]

    plain = ["NO.", "ITEM NO.", "DESCRIPTION", "QTY", "PACKAGES", "G.W.", "1", "YT-M001", "CERAMIC MUG 350ML WHITE", "2400 PCS", "30", "CTNS", "600.00", "TOTAL PACKAGES: 30 CTNS"]
    fallback = _sequential_packing_table(plain)
    assert fallback[1] == "1   YT-M001   CERAMIC MUG 350ML WHITE   2400 PCS   30 CTNS   600.00"
    try:
        _sequential_packing_table(plain[:-2] + ["UNKNOWN", plain[-1]])
    except ValueError:
        pass
    else:
        raise AssertionError("Uncertain table cell was accepted")
    print("OCR table adapter guards passed")


if __name__ == "__main__":
    main()
