"""单证类型判别。

契约：判不出来给 null。宁可给 null，也不要瞎猜 —— 猜错会让
`NOT_IN_DOC` / `MISSING_IN_DOC` 的判定跟着一起错。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import DocType

# 关键词 -> 类型。命中越强分越高。
_KEYWORDS: list[tuple[str, tuple[str, ...], int]] = [
    (DocType.BILL_OF_LADING.value, ("BILL OF LADING", "B/L NO", "B/L NO.", "提单", "OCEAN BILL"), 3),
    (DocType.PACKING_LIST.value, ("PACKING LIST", "装箱单", "PACKING SPEC"), 3),
    (DocType.COMMERCIAL_INVOICE.value, ("COMMERCIAL INVOICE", "商业发票", "INVOICE NO", "INVOICE NUMBER"), 3),
    (DocType.CUSTOMS_DECLARATION.value, ("CUSTOMS DECLARATION", "报关单", "DECLARATION NO"), 3),
    (DocType.CERTIFICATE_OF_ORIGIN.value, ("CERTIFICATE OF ORIGIN", "原产地证", "C/O NO"), 3),
    (DocType.INSURANCE_POLICY.value, ("INSURANCE POLICY", "保险单"), 3),
]

# 文件名里的线索，权重低一档：文本里没有明确标题时才靠它
_FILENAME_HINTS: list[tuple[str, tuple[str, ...], int]] = [
    (DocType.BILL_OF_LADING.value, ("bill_of_lading", "bill-of-lading", "bl", "提单"), 2),
    (DocType.PACKING_LIST.value, ("packing", "pl", "装箱单"), 2),
    (DocType.COMMERCIAL_INVOICE.value, ("invoice", "inv", "发票"), 2),
    (DocType.CUSTOMS_DECLARATION.value, ("customs", "declaration", "报关"), 2),
    (DocType.CERTIFICATE_OF_ORIGIN.value, ("origin", "co", "原产地"), 2),
    (DocType.INSURANCE_POLICY.value, ("insurance", "保险"), 2),
]


def classify(text: str, filename: str = "") -> str | None:
    """返回 DocType 的值，判不出来返回 None。"""
    upper = (text or "").upper()
    # The current contract has no PROFORMA_INVOICE enum. Keep an explicitly
    # titled proforma out of the commercial-invoice profile until agreed.
    if re.search(r"\bPRO\s*FORMA\s+INVOICE\b|\bPROFORMA\s+INVOICE\b", upper):
        return DocType.OTHER.value
    scores: dict[str, int] = {}

    for doc_type, keywords, weight in _KEYWORDS:
        for kw in keywords:
            if kw in upper:
                scores[doc_type] = scores.get(doc_type, 0) + weight
                break

    if scores:
        best = max(scores, key=lambda k: scores[k])
        # 同分时按下列固定顺序取，保证结果稳定可复现
        order = [t for t, _, _ in _KEYWORDS]
        if list(scores.values()).count(scores[best]) > 1:
            tied = sorted([k for k, v in scores.items() if v == scores[best]], key=order.index)
            return tied[0]
        return best

    name = Path(filename or "").stem.lower()
    for doc_type, hints, weight in _FILENAME_HINTS:
        if any((re.search(r"(?:^|[-_])" + re.escape(h) + r"(?:$|[-_])", name)
                if len(h) <= 3 else h in name) for h in hints):
            return doc_type

    return None


def has_reference(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text or "", re.I))
