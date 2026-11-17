"""Structure-aware chunking with page provenance.

- Accumulates paragraphs up to `chunk_size` tokens with `overlap` tokens carried forward.
- Never splits inside a sentence unless a single sentence exceeds the chunk size.
- Headings start a new logical section and are recorded on each chunk.
- `legal=True` forces a chunk boundary at every statutory section ("309. Robbery.—", "Section 309").
- Each chunk records `page_spans`: the character range of `text` that came from each page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingestion.extractors import Block

_TOKEN = re.compile(r"[\wऀ-ॿ]+|[^\w\s]", re.UNICODE)
_SENTENCE = re.compile(r"(?<=[.!?।])\s+(?=[A-Z0-9\"'(ऀ-ॿ])")
LEGAL_SECTION = re.compile(r"^\s*(?:Section\s+)?(\d{1,3}[A-Z]?)\s*\.\s*(?:\(\d+\)\s*)?[A-Z(\"ऀ-ॿ]")


def count_tokens(text: str) -> int:
    """Approximate token count (word pieces + punctuation). Model-independent and deterministic."""
    return len(_TOKEN.findall(text))


@dataclass
class Unit:
    text: str
    page: int
    tokens: int


@dataclass
class Chunk:
    text: str
    page_start: int
    page_end: int
    page_spans: list[dict] = field(default_factory=list)
    heading: str | None = None
    section_number: str | None = None
    token_count: int = 0


def _split_long(text: str, page: int, max_tokens: int) -> list[Unit]:
    if count_tokens(text) <= max_tokens:
        return [Unit(text, page, count_tokens(text))]
    units, buf = [], ""
    for sent in _SENTENCE.split(text):
        cand = (buf + " " + sent).strip()
        if buf and count_tokens(cand) > max_tokens:
            units.append(Unit(buf, page, count_tokens(buf)))
            buf = sent
        else:
            buf = cand
    if buf:
        # A single enormous sentence: hard-split on words.
        while count_tokens(buf) > max_tokens:
            words = buf.split(" ")
            cut = max(1, int(len(words) * max_tokens / count_tokens(buf)))
            part = " ".join(words[:cut])
            units.append(Unit(part, page, count_tokens(part)))
            buf = " ".join(words[cut:])
        if buf:
            units.append(Unit(buf, page, count_tokens(buf)))
    return units


def _build(units: list[Unit], heading: str | None, section: str | None) -> Chunk:
    parts, spans, pos = [], [], 0
    for u in units:
        if parts:
            pos += 2
        start = pos
        parts.append(u.text)
        pos += len(u.text)
        if spans and spans[-1]["page"] == u.page:
            spans[-1]["end"] = pos
        else:
            spans.append({"page": u.page, "start": start, "end": pos})
    text = "\n\n".join(parts)
    return Chunk(
        text=text,
        page_start=min(u.page for u in units),
        page_end=max(u.page for u in units),
        page_spans=spans,
        heading=heading,
        section_number=section,
        token_count=count_tokens(text),
    )


def chunk_blocks(blocks: list[Block], chunk_size: int = 700, overlap: int = 120, legal: bool = False) -> list[Chunk]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    chunks: list[Chunk] = []
    current: list[Unit] = []
    cur_tokens = 0
    min_section_tokens = chunk_size // 4
    fresh = 0  # units added since the last flush (carried overlap units don't count)
    heading: str | None = None
    section: str | None = None

    def flush(carry: bool):
        nonlocal current, cur_tokens, fresh
        if not current or fresh == 0:
            current, cur_tokens, fresh = [], 0, 0
            return
        fresh = 0
        chunks.append(_build(current, heading, section))
        if not carry or overlap == 0:
            current, cur_tokens = [], 0
            return
        tail, t = [], 0
        for u in reversed(current):
            if t + u.tokens > overlap:
                break
            tail.insert(0, u)
            t += u.tokens
        if not tail:  # last unit larger than overlap: carry its trailing words
            last = current[-1]
            words = last.text.split(" ")
            keep = max(1, int(len(words) * overlap / max(1, last.tokens)))
            txt = " ".join(words[-keep:])
            tail = [Unit(txt, last.page, count_tokens(txt))]
            t = tail[0].tokens
        current, cur_tokens = tail, t

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        m = LEGAL_SECTION.match(text) if legal else None
        if (m and (section is not None or cur_tokens >= 50)) or (block.is_heading and cur_tokens >= min_section_tokens):
            # New section: close the current chunk without overlap so sections stay clean.
            # (Tiny sections are merged with the next one; statutory sections always start a new chunk.)
            flush(carry=False)
        if block.is_heading and (not current or fresh == 0 or heading is None):
            heading = text[:300]
        if m:
            section = m.group(1)
            if not block.is_heading:
                heading = text.split("\n")[0][:300]
        for unit in _split_long(text, block.page, chunk_size):
            if current and cur_tokens + unit.tokens > chunk_size:
                flush(carry=True)
            current.append(unit)
            cur_tokens += unit.tokens
            fresh += 1
    flush(carry=False)
    return chunks
