"""Rule-based entity extraction tuned for Indian police documents.

Every entity carries its exact character span, so it is always traceable to source text.
Rules are deterministic and auditable; extraction confidence reflects pattern specificity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS = {
    m: i + 1
    for i, names in enumerate([
        ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",),
        ("june", "jun"), ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"),
        ("october", "oct"), ("november", "nov"), ("december", "dec"),
    ])
    for m in names
}
_MONTH_RE = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"

ACTS = (r"BNSS|BNS|BSA|IPC|Cr\.?P\.?C\.?|Bharatiya Nyaya Sanhita(?:,? 2023)?|Bharatiya Nagarik Suraksha Sanhita(?:,? 2023)?|"
        r"Bharatiya Sakshya Adhiniyam(?:,? 2023)?|Indian Penal Code(?:,? 1860)?|Code of Criminal Procedure(?:,? 1973)?|"
        r"Indian Evidence Act(?:,? 1872)?|Arms Act(?:,? 1959)?|IT Act|Information Technology Act(?:,? 2000)?")
_SEC_ITEM = r"\d{1,3}[A-Z]?(?:\(\d+\))?(?:\([a-z]\))?"

PATTERNS: list[tuple[str, re.Pattern, float]] = [
    ("FIR_NUMBER", re.compile(r"\bFIR\s*(?:No\.?|Number|#)?\s*[:.\-]?\s*(\d{1,5}\s*/\s*\d{4}|[A-Z]{2}-\d{4}-\d{3,})", re.I), 0.95),
    ("CASE_ID", re.compile(r"\b[A-Z]{2}-\d{4}-\d{3,}\b"), 0.95),
    ("LEGAL_SECTION", re.compile(
        rf"\b(?:Sections?|Secs?\.|u/s)\s+{_SEC_ITEM}(?:\s*(?:,|and|&|/)\s*{_SEC_ITEM})*(?:\s+(?:of\s+)?(?:the\s+)?(?:{ACTS}))?", re.I), 0.9),
    ("VEHICLE_NUMBER", re.compile(r"\b[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{1,3}[ -]?\d{4}\b"), 0.9),
    ("PHONE", re.compile(r"(?<![\d-])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?![\d-])"), 0.85),
    ("DATE", re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b"), 0.9),
    ("DATE", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_RE},?\s+(\d{{4}})\b", re.I), 0.95),
    ("DATE", re.compile(rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), 0.95),
    ("TIME", re.compile(r"\b(?:at\s+)?(?:about\s+|around\s+|approximately\s+)?(\d{1,2})[:.](\d{2})\s*(a\.?m\.?|p\.?m\.?|hrs\.?|hours)(?![a-z])", re.I), 0.9),
    ("TIME", re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(?:a\.?m|p\.?m|hrs|hours))"), 0.8),
    ("TIME", re.compile(r"\b(\d{1,2})\s*(a\.m\.|p\.m\.|am|pm)(?![a-z])", re.I), 0.8),
    ("AMOUNT", re.compile(r"(?:Rs\.?|INR|₹)\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:lakh|lakhs|crore|crores))?(?:\s*/-)?", re.I), 0.9),
    ("PERSON", re.compile(
        r"\b(?:Shri|Smt\.?|Sh\.|Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Kumari|Km\.|Sub-Inspector|Inspector|Head Constable|Constable|"
        r"SI|ASI|SHO|HC|Ct\.) +((?:[A-Z][a-z]+)(?: [A-Z][a-z]+){0,3})"), 0.85),
    ("PERSON", re.compile(r"\b(?:Name(?: of (?:the )?(?:witness|complainant|informant|accused|suspect))?|Complainant|Witness|"
                          r"Informant|Accused|Suspect|Investigating Officer|Recorded by|Prepared by)(?: name)?\s*:\s*"
                          r"(?:(?:SI|ASI|SHO|Inspector|Shri|Smt\.?) )?((?:[A-Z][a-z]+)(?: [A-Z][a-z]+){0,3})"), 0.8),
    ("PERSON", re.compile(r"\b(?:[Ww]itness(?:es)?|[Ss]alesman|[Cc]omplainant) ((?:[A-Z][a-z]+)(?: [A-Z][a-z]+){1,3})"), 0.75),
    ("LOCATION", re.compile(r"\b(?:Place of (?:occurrence|incident)|Location|Address|Scene of crime)\s*:\s*([^\n;]{4,140})", re.I), 0.85),
    ("LOCATION", re.compile(
        r"\b(?:at|near|in|from|towards)\s+((?:[A-Z][a-z]+ ){1,3}(?:Market|Bazaar|Road|Marg|Chowk|Colony|Nagar|Circle|Gate|"
        r"Station|Street|Lane|Mall|Complex|Highway|Square|Vihar|Puri|Bagh|Enclave))\b"), 0.75),
    ("POLICE_STATION", re.compile(r"\b(?:Police Station|P\.S\.|PS)\s*[:\-]?\s*((?:[A-Z][a-z]+)(?: [A-Z][a-z]+){0,2})"), 0.85),
]

# Groups that hold the entity value (others use the whole match)
VALUE_GROUP = {"FIR_NUMBER": 1, "PERSON": 1, "LOCATION": 1, "POLICE_STATION": 1}

_SENT_BOUND = re.compile(r"(?<=[.!?।])\s+|\n+")
_HONORIFIC = re.compile(r"^(?:shri|smt\.?|sh\.|mr\.?|mrs\.?|ms\.?|dr\.?|kumari|km\.)\s+", re.I)
_NOT_NAMES = {"The", "This", "That", "Police", "Station", "Report", "Statement", "Case", "District", "Section"}


@dataclass
class EntityMatch:
    entity_type: str
    value: str
    normalized: str
    start: int
    end: int
    confidence: float
    context: str


def normalize_date(m: re.Match, pattern_index: int) -> str | None:
    g = m.groups()
    try:
        if g[0].isdigit() and g[1].isdigit():  # dd/mm/yyyy
            d, mo, y = int(g[0]), int(g[1]), int(g[2])
        elif g[0].isdigit():  # 12 March 2026
            d, mo, y = int(g[0]), MONTHS[g[1].lower().rstrip(".")], int(g[2])
        else:  # March 12, 2026
            mo, d, y = MONTHS[g[0].lower().rstrip(".")], int(g[1]), int(g[2])
        return date(y, mo, d).isoformat()
    except (ValueError, KeyError):
        return None


def normalize_time(m: re.Match) -> str | None:
    g = [x for x in m.groups() if x is not None]
    try:
        h = int(g[0])
        mi = int(g[1]) if len(g) > 1 and g[1].isdigit() else 0
        suffix = (g[-1] if not g[-1].isdigit() else "").lower().replace(".", "")
        if suffix in ("pm",) and h < 12:
            h += 12
        if suffix in ("am",) and h == 12:
            h = 0
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            return None
        return f"{h:02d}:{mi:02d}"
    except (ValueError, IndexError):
        return None


def sentence_around(text: str, start: int, end: int, max_len: int = 400) -> str:
    left = max((m.end() for m in _SENT_BOUND.finditer(text, 0, start)), default=0)
    nxt = _SENT_BOUND.search(text, end)
    right = nxt.start() if nxt else len(text)
    s = text[left:right].strip()
    return s if len(s) <= max_len else text[max(0, start - 150): min(len(text), end + 150)].strip()


def extract_entities(text: str) -> list[EntityMatch]:
    found: list[EntityMatch] = []
    taken: list[tuple[int, int, str]] = []
    for idx, (etype, pattern, conf) in enumerate(PATTERNS):
        for m in pattern.finditer(text):
            grp = VALUE_GROUP.get(etype, 0)
            start, end = m.span(grp)
            value = m.group(grp).strip().rstrip(".,")
            end = start + len(value)
            if etype == "DATE":
                norm = normalize_date(m, idx)
                if not norm:
                    continue
            elif etype == "TIME":
                norm = normalize_time(m)
                if not norm:
                    continue
                start, end = m.span()
                value = m.group(0).strip()
                if value.lower().startswith("at "):
                    start, value = start + 3, value[3:]
            elif etype == "PERSON":
                value = _HONORIFIC.sub("", value)
                if value.split()[0] in _NOT_NAMES:
                    continue
                norm = value.lower()
            elif etype in ("VEHICLE_NUMBER", "PHONE"):
                norm = re.sub(r"[\s-]", "", value).upper()
                if etype == "PHONE":
                    norm = norm[-10:]
            elif etype == "FIR_NUMBER":
                norm = re.sub(r"\s", "", value).upper()
            else:
                norm = re.sub(r"\s+", " ", value).strip().lower()
            # Avoid overlapping duplicates of the same type (e.g. two TIME patterns)
            if any(etype == t and not (end <= s or start >= e) for s, e, t in taken):
                continue
            taken.append((start, end, etype))
            found.append(EntityMatch(etype, value, norm, start, end, conf, sentence_around(text, start, end)))
    found.sort(key=lambda e: e.start)
    return found


def page_for_offset(page_spans: list[dict], offset: int, default: int) -> int:
    for span in page_spans or []:
        if span["start"] <= offset < span["end"] + 2:
            return span["page"]
    return default
