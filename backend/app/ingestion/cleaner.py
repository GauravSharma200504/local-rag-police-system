"""Conservative text cleaning. Never drops content; only normalizes whitespace and line wrapping."""
from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"[ \t  -   　]+")
_HYPHEN_WRAP = re.compile(r"([a-z])-\n([a-z])")
_FIELD = re.compile(r"^[A-Z][A-Za-z ./()&-]{1,45}:\s")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"}


def clean_paragraph(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    for lig, rep in _LIGATURES.items():
        text = text.replace(lig, rep)
    text = text.replace("​", "").replace("﻿", "")
    text = _HYPHEN_WRAP.sub(r"\1\2", text)
    lines = [_SPACES.sub(" ", ln).strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    # Keep list items / table rows / numbered clauses on their own line, join soft-wrapped lines.
    out = [lines[0]]
    for ln in lines[1:]:
        if (re.match(r"^(\(?[0-9ivxa-z]{1,4}[.)]|[-•*]|\|)\s", ln, re.I) or "|" in ln or out[-1].endswith(":")
                or _FIELD.match(ln)):
            out.append(ln)
        else:
            out[-1] = out[-1] + " " + ln
    return "\n".join(out)


def detect_language(text: str) -> str:
    dev = len(_DEVANAGARI.findall(text))
    lat = len(_LATIN.findall(text))
    if dev == 0 and lat == 0:
        return "unknown"
    ratio = dev / (dev + lat)
    if ratio > 0.7:
        return "hi"
    if ratio > 0.1:
        return "mixed"
    return "en"
