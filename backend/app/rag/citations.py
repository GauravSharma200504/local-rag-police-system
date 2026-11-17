"""Citation validation.

Each [S#] marker in the generated answer is checked against the actual retrieved chunk:
1. The label must exist in the source list (otherwise removed as fabricated).
2. The cited sentence must be lexically supported by the chunk: the share of its content words and
   *all* of its numbers (dates, times, amounts, identifiers) found in the chunk must reach the threshold.
   Unsupported citations are removed and the sentence is flagged.
3. The supporting passage (best-matching sentences in the chunk) and its page are attached.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.intelligence.entities import page_for_offset
from app.retrieval.types import Candidate

MARKER = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")
_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")
_WORD = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)
_NUM = re.compile(r"\d+")
_STOP = set("""a an the of in on at to for and or is are was were be been being by with from that this these those it its as
which who whom whose what when where why how not no yes also than then there their they he she his her him we our you your
said says stated states according per document documents source sources page pages mentioned mentions report reports
has have had do does did can could would should may might will shall into about over under after before during""".split())

ABSTAIN_TOKEN = "INSUFFICIENT_EVIDENCE"
ABSTAIN_MESSAGE = ("Sufficient evidence was not found in the authorized documents to answer this question. "
                   "Try rephrasing, widening the case/document filters, or uploading the relevant document.")


@dataclass
class ValidatedCitation:
    label: str
    candidate: Candidate
    page: int
    passage: str
    support: float


@dataclass
class ValidationResult:
    text: str
    citations: list[ValidatedCitation] = field(default_factory=list)
    removed_invalid_labels: list[str] = field(default_factory=list)
    unsupported_sentences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def content_words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP and (len(w) > 2 or w.isdigit())}


def numbers(text: str) -> set[str]:
    return {n.lstrip("0") or "0" for n in _NUM.findall(text)}


def support_score(sentence: str, chunk_text: str) -> float:
    s_words = content_words(MARKER.sub("", sentence))
    if not s_words:
        return 1.0
    c_words = content_words(chunk_text)
    word_cov = len(s_words & c_words) / len(s_words)
    s_nums = numbers(MARKER.sub("", sentence))
    if s_nums:
        num_cov = len(s_nums & numbers(chunk_text)) / len(s_nums)
        if num_cov < 1.0:
            # Any number not present in the source is a strong signal of an unsupported claim.
            return min(word_cov, num_cov) * 0.5
    return word_cov


def best_passage(sentence: str, cand: Candidate, max_chars: int = 420) -> tuple[str, int]:
    """Return the chunk sentence window best supporting `sentence`, and the page it is on."""
    text = cand.text
    spans, pos = [], 0
    for m in _SENT_SPLIT.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    target = content_words(sentence)
    best, best_score = spans[0], -1.0
    for i, (a, b) in enumerate(spans):
        window_end = spans[i + 1][1] if i + 1 < len(spans) and b - a < 120 else b
        score = len(target & content_words(text[a:window_end]))
        if score > best_score:
            best, best_score = (a, window_end), score
    a, b = best
    passage = text[a:b].strip()
    if len(passage) > max_chars:
        passage = passage[:max_chars].rsplit(" ", 1)[0] + "…"
    return passage, page_for_offset(cand.page_spans, a, cand.page_start)


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s.strip()]


def _labels(marker_body: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,;]", marker_body)]


_META = re.compile(r"(not (mentioned|found|stated|specified|available|provided)|no (information|mention|evidence|record)|"
                   r"do(es)? not (contain|mention|specify|state)|unclear|insufficient|cannot be determined|"
                   r"in summary|the following|differences?:|summary:)", re.I)


def validate(answer: str, sources: list[Candidate], threshold: float = 0.35) -> ValidationResult:
    by_label = {f"S{i + 1}": c for i, c in enumerate(sources)}
    result = ValidationResult(text=answer)
    cited: dict[str, ValidatedCitation] = {}
    out_lines = []
    for line in answer.split("\n"):
        new_sents = []
        for sent in split_sentences(line) if line.strip() else [""]:
            kept_labels = []
            for m in MARKER.finditer(sent):
                for lab in _labels(m.group(1)):
                    cand = by_label.get(lab)
                    if cand is None:
                        result.removed_invalid_labels.append(lab)
                        continue
                    score = support_score(sent, cand.text)
                    if score < threshold:
                        continue
                    kept_labels.append(lab)
                    passage, page = best_passage(sent, cand)
                    prev = cited.get(lab)
                    if prev is None or score > prev.support:
                        cited[lab] = ValidatedCitation(lab, cand, page, passage, round(score, 3))
            bare = MARKER.sub("", sent).strip()
            had_markers = bool(MARKER.search(sent))
            if bare and not kept_labels and len(content_words(bare)) >= 3 and not _META.search(bare):
                result.unsupported_sentences.append(bare)
            if had_markers:
                bare = bare.rstrip()
                suffix = "".join(f"[{lab}]" for lab in dict.fromkeys(kept_labels))
                if bare and bare[-1] in ".!?।" and suffix:
                    bare = f"{bare[:-1]} {suffix}{bare[-1]}"
                elif suffix:
                    bare = f"{bare} {suffix}"
            new_sents.append(bare if had_markers else sent)
        out_lines.append(" ".join(s for s in new_sents))
    result.text = "\n".join(out_lines).strip()
    result.citations = sorted(cited.values(), key=lambda c: int(c.label[1:]))
    if result.removed_invalid_labels:
        result.warnings.append(
            f"Removed {len(result.removed_invalid_labels)} citation(s) to non-existent sources: "
            + ", ".join(sorted(set(result.removed_invalid_labels))))
    if result.unsupported_sentences:
        result.warnings.append(
            f"{len(result.unsupported_sentences)} statement(s) could not be verified against the cited sources "
            "and are marked as unverified.")
    return result
