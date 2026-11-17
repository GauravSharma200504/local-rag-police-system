"""Reciprocal Rank Fusion and duplicate removal."""
from __future__ import annotations

import re

from app.retrieval.types import Candidate

_WORD = re.compile(r"\w+", re.UNICODE)


def reciprocal_rank_fusion(ranked_lists: list[list[Candidate]], k: int = 60) -> list[Candidate]:
    """RRF(d) = Σ_lists 1 / (k + rank_list(d)).  (Cormack, Clarke & Büttcher, SIGIR 2009)

    Ranks are 1-based positions within each input list. Score dictionaries from every list
    are merged so later stages can show dense and sparse evidence side by side.
    """
    fused: dict = {}
    for lst in ranked_lists:
        for rank, cand in enumerate(lst, start=1):
            entry = fused.get(cand.chunk_id)
            if entry is None:
                entry = fused[cand.chunk_id] = cand
                entry.scores.setdefault("rrf", 0.0)
            else:
                entry.scores.update({kk: v for kk, v in cand.scores.items() if kk not in entry.scores})
            entry.scores["rrf"] += 1.0 / (k + rank)
    out = sorted(fused.values(), key=lambda c: c.scores["rrf"], reverse=True)
    for i, c in enumerate(out, start=1):
        c.scores["rrf_rank"] = i
    return out


def _shingles(text: str) -> set[str]:
    words = [w.lower() for w in _WORD.findall(text)]
    return {" ".join(words[i:i + 3]) for i in range(max(1, len(words) - 2))}


def remove_duplicates(cands: list[Candidate], threshold: float = 0.9) -> list[Candidate]:
    """Drop candidates whose 3-word shingle Jaccard similarity with a higher-ranked one exceeds threshold."""
    kept: list[tuple[Candidate, set[str]]] = []
    for c in cands:
        sh = _shingles(c.text)
        if any(len(sh & s) / max(1, len(sh | s)) >= threshold for _, s in kept):
            continue
        kept.append((c, sh))
    return [c for c, _ in kept]
