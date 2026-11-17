"""Sparse (keyword) retrieval using PostgreSQL full-text search.

The query is tokenized and each token becomes a plainto_tsquery under both the 'english'
(stemmed) and 'simple' (exact; works for Hindi and identifiers like RJ-2026-001) configurations.
Tokens are OR-combined and ranked with ts_rank_cd, which rewards term density and proximity.
"""
from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DocumentChunk, User
from app.retrieval.base_query import row_to_candidate, scoped_select
from app.retrieval.types import Candidate, RetrievalFilters

_TOKEN = re.compile(r"[A-Za-z0-9ऀ-ॿ]+(?:[-/][A-Za-z0-9ऀ-ॿ]+)*", re.UNICODE)
STOP = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "is", "are", "was", "were", "be", "by",
    "with", "what", "which", "who", "whom", "when", "where", "why", "how", "did", "does", "do", "this", "that",
    "these", "those", "it", "its", "as", "from", "about", "any", "all", "there", "their", "me", "tell", "give",
    "please", "list", "show", "find", "according", "mentioned", "document", "documents",
}


def query_tokens(query: str, max_tokens: int = 32) -> list[str]:
    seen, out = set(), []
    for t in _TOKEN.findall(query):
        low = t.lower()
        if low in STOP or low in seen or (len(low) < 2 and not low.isdigit()):
            continue
        seen.add(low)
        out.append(t)
    return out[:max_tokens]


def build_tsquery(tokens: list[str]):
    q = None
    for t in tokens:
        for cfg in ("english", "simple"):
            part = func.plainto_tsquery(cfg, t)
            q = part if q is None else q.op("||")(part)
    return q


def sparse_search(db: Session, user: User, query: str, filters: RetrievalFilters, top_k: int = 20) -> list[Candidate]:
    tokens = query_tokens(query)
    if not tokens:
        return []
    tsq = build_tsquery(tokens)
    rank = func.ts_rank_cd(DocumentChunk.tsv, tsq, 1)  # normalization 1: divide by 1 + log(length)
    stmt = (
        scoped_select(user, filters, rank.label("rank"))
        .where(DocumentChunk.tsv.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(top_k)
    )
    results = []
    for i, row in enumerate(db.execute(stmt).all(), start=1):
        c = row_to_candidate(row)
        c.scores.update(sparse_score=float(row.rank), sparse_rank=i)
        results.append(c)
    return results
