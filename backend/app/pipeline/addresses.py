"""Optional party addresses: bounded labelled blocks, never guessed column ownership."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

_ROLES = {
    "shipper": r"SHIPPER|SELLER|EXPORTER|发货人|卖方|出口商",
    "consignee": r"CONSIGNEE|BUYER|IMPORTER|收货人|买方|进口商",
}
_ALL_ROLES = "|".join(_ROLES.values())
_PARTY = re.compile(
    rf"^(?:{_ALL_ROLES})(?![A-Za-z])(?:[ \t]*/[ \t]*(?:{_ALL_ROLES}))?"
    r"(?:[ \t]+(?:NAME(?:[ \t]+AND[ \t]+ADDRESS)?|AND[ \t]+ADDRESS|&[ \t]*ADDRESS))?"
    r"[ \t]*[:：]?[ \t]*", re.I,
)
_STOP = re.compile(
    r"^(?:EMAIL|E-MAIL|TEL(?:EPHONE)?|PHONE|FAX|CONTACT|ATTN)"
    r"(?:[ \t]*[:：]|[ \t]*$|[ \t]+(?=[+\d(]))|"
    r"^(?:INCOTERMS?|PAYMENT(?:\s+TERMS)?|PORT\s+OF\s+(?:LOADING|DISCHARGE|DESTINATION)|"
    r"DESTINATION|SHIPPING\s+MARK|ORIGIN|VESSEL(?:\s*/\s*FLIGHT)?|FLIGHT|"
    r"CURRENCY|DOCUMENT\s+NO|INVOICE\s+NO|DATE|SHIPMENT|"
    r"DESCRIPTION(?:\s*/\s*SKU)?|SKU|HS\s+CODE|QUANTITY|QTY|PACKAGES|PKGS|"
    r"(?:NET|GROSS)(?:\s+(?:WEIGHT|WT))?|TOTAL(?:\s+(?:AMOUNT|VALUE|PACKAGES|CARTONS|QUANTITY))?|"
    r"AMOUNT|UNIT\s+PRICE|邮箱|电话|传真|联系人|付款|起运港|目的港|"
    r"目的国|日期|数量|件数|毛重|净重|金额|合计)(?:[ \t]*[:：]|[ \t]*$)|"
    r"^NO\.(?=[ \t]*(?:$|DESCRIPTION|ITEM|SKU))", re.I,
)
_STREET = re.compile(
    r"\b(?:ROAD|RD\.?|STREET|ST\.?|AVENUE|AVE\.?|LANE|LN\.?|DRIVE|DR\.?|"
    r"BOULEVARD|BLVD\.?|WAY|PLAZA|COURT|HIGHWAY|HWY|BUILDING|BLDG|"
    r"INDUSTRIAL\s+(?:PARK|ESTATE)|P\.?\s*O\.?\s*BOX)\b|[路街巷弄号號]", re.I,
)
_COMPANY = re.compile(r"\b(?:LTD|LIMITED|INC|LLC|GMBH|CORPORATION|CO|COMPANY|CORP|PLC|PTY|GROUP)\b|公司", re.I)
_CONTACT = re.compile(r"\b(?:EMAIL|E-MAIL|TEL|TELEPHONE|PHONE|FAX|CONTACT)\s*[:：]|邮箱|电话|传真", re.I)
_MAX_LINES = 12
_MAX_VALUE = 2000
_NON_VALUES = {"N/A", "NA", "UNKNOWN", "TBD", "NOT PROVIDED", "NOT AVAILABLE",
               "ADDRESS", "NAME", "CITY", "STATE", "COUNTRY", "POSTCODE", "ZIP CODE",
               "SKU", "地址", "名称", "邮编", "-", "*****"}


@dataclass
class AddressMatch:
    raw_text: str
    raw_value: str | None
    unreadable: bool = False


def normalize_address(raw: str | None) -> str | None:
    """Only case, Unicode width, whitespace and comma spacing; keep every digit."""
    if raw is None:
        return None
    text = unicodedata.normalize("NFKC", str(raw)).strip()
    if not text or len(text) > _MAX_VALUE or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
        return None
    if all(line.strip().upper() in _NON_VALUES for line in text.splitlines()):
        return None
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text.upper()


def extract_address(text: str, role: str) -> AddressMatch | None:
    """Explicit address labels or a street inside one sequential party block.

    Flattened side-by-side parties have no reliable column ownership. Keep an
    unreadable field instead of borrowing the other party's street. No address
    is required merely because a company name appeared.
    """
    roles = _ROLES[role]
    explicit = re.compile(
        rf"^(?:(?:{roles})(?![A-Za-z])(?:['’]S)?[ \t]*(?:ADDRESS|地址)|"
        rf"ADDRESS[ \t]+OF[ \t]+(?:{roles})(?![A-Za-z]))[ \t]*[:：]?[ \t]*", re.I,
    )
    party = re.compile(
        rf"^(?:{roles})(?![A-Za-z])(?:[ \t]*/[ \t]*(?:{roles}))?"
        r"(?:[ \t]+(?:NAME(?:[ \t]+AND[ \t]+ADDRESS)?|AND[ \t]+ADDRESS|&[ \t]*ADDRESS))?"
        r"[ \t]*[:：]?[ \t]*", re.I,
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    role_headers = {key: re.compile(rf"(?<![A-Za-z])(?:{value})(?![A-Za-z])[ \t]*(?:/|:|：)", re.I)
                    for key, value in _ROLES.items()}
    for index, line in enumerate(lines):
        if all(pattern.search(line) for pattern in role_headers.values()):
            return AddressMatch(line, None, True)
        if index + 1 < len(lines) and _PARTY.fullmatch(line) and _PARTY.fullmatch(lines[index + 1]):
            pair = lines[index:index + 2]
            if all(any(re.match(rf"(?:{value})(?![A-Za-z])", label, re.I) for label in pair)
                   for value in _ROLES.values()):
                return AddressMatch("\n".join(pair), None, True)
    matches: list[AddressMatch] = []
    for index, label in enumerate(lines):
        header = explicit.match(label) or party.match(label)
        if header is None:
            continue
        is_explicit = explicit.match(label) is not None
        tail = label[header.end():].strip()
        body = [tail] if tail else []
        end = index + 1
        while end < len(lines) and not (_PARTY.match(lines[end]) or _STOP.match(lines[end])):
            body.append(lines[end])
            end += 1
            if len(body) > _MAX_LINES:
                break
        evidence = "\n".join(lines[index:end])
        # A second role on the same line, pipes, or adjacent unvalued role
        # headers indicate columns that have been flattened without ownership.
        ambiguous = ("|" in evidence or "<" in evidence or
                     re.search(rf"(?:{_ALL_ROLES})[ \t]*(?:/|:|：)", tail, re.I) or
                     (not body and end < len(lines) and _PARTY.match(lines[end])))
        if ambiguous or len(body) > _MAX_LINES:
            matches.append(AddressMatch(evidence, None, True))
            continue
        if is_explicit:
            address = body
        else:
            # Only the immediate street after an optional company name is
            # eligible. Never scan unrelated later text for a plausible value.
            start = next((i for i, line in enumerate(body[:2])
                          if _STREET.search(line) and re.search(r"\d", line)
                          and not _COMPANY.search(line)), None)
            if start is None:
                continue
            address = body[start:]
        raw = "\n".join(address).strip()
        if (not raw or len(raw) > _MAX_VALUE or _STOP.match(raw) or
                raw.startswith("/") or "@" in raw or _CONTACT.search(raw) or
                normalize_address(raw) is None or
                (_COMPANY.search(raw) and not _STREET.search(raw)) or
                any(_PARTY.match(line) or _STOP.match(line) for line in address)):
            matches.append(AddressMatch(evidence, None, True))
        else:
            matches.append(AddressMatch(evidence, raw))
    if not matches:
        return None
    if any(match.unreadable for match in matches) or len({normalize_address(m.raw_value) for m in matches}) != 1:
        return AddressMatch("\n".join(m.raw_text for m in matches), None, True)
    return matches[0]
