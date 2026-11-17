"""Retrieval orchestration for the three experimental configurations.

  vector   : dense retrieval only                                  (Baseline 1)
  hybrid   : dense + sparse → RRF                                  (Baseline 2)
  proposed : dense + sparse → RRF → cross-encoder rerank → threshold (Proposed; citation validation in rag/)
"""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.ingestion.embeddings import Embedder, get_embedder
from app.models import User
from app.retrieval.dense import dense_search
from app.retrieval.fusion import reciprocal_rank_fusion, remove_duplicates
from app.retrieval.reranker import Reranker, get_reranker
from app.retrieval.sparse import sparse_search
from app.retrieval.types import RetrievalFilters, RetrievalResult
from app.services.runtime_settings import RetrievalParams

CONFIGS = ("vector", "hybrid", "proposed")


def normalize_query(q: str) -> str:
    """Whitespace-only normalization: the meaning of the query is never changed."""
    return " ".join(q.split())


def retrieve(db: Session, user: User, query: str, params: RetrievalParams, filters: RetrievalFilters | None = None,
             config: str = "proposed", embedder: Embedder | None = None, reranker: Reranker | None = None,
             final_k: int | None = None) -> RetrievalResult:
    if config not in CONFIGS:
        raise ValueError(f"Unknown retrieval config '{config}'. Choose one of {CONFIGS}")
    filters = filters or RetrievalFilters()
    query = normalize_query(query)
    final_k = final_k or params.rerank_top_k
    embedder = embedder or get_embedder()
    timings, counts = {}, {}

    t = time.perf_counter()
    dense = dense_search(db, user, query, embedder, filters, params.retrieval_top_k, params.dense_similarity_threshold)
    timings["dense_ms"] = (time.perf_counter() - t) * 1000
    counts["dense"] = len(dense)

    if config == "vector":
        cands = remove_duplicates(dense)[:final_k]
    else:
        t = time.perf_counter()
        sparse = sparse_search(db, user, query, filters, params.retrieval_top_k)
        timings["sparse_ms"] = (time.perf_counter() - t) * 1000
        counts["sparse"] = len(sparse)

        t = time.perf_counter()
        fused = remove_duplicates(reciprocal_rank_fusion([dense, sparse], k=params.rrf_k))
        timings["fusion_ms"] = (time.perf_counter() - t) * 1000
        counts["fused"] = len(fused)

        if config == "hybrid":
            cands = fused[:final_k]
        else:
            t = time.perf_counter()
            rr = reranker or get_reranker()
            cands = rr.rerank(query, fused[:params.retrieval_top_k], top_k=final_k,
                              min_score=params.rerank_score_threshold if rr.name != "none" else None)
            timings["rerank_ms"] = (time.perf_counter() - t) * 1000
            counts["reranked"] = len(cands)
    timings["total_ms"] = sum(timings.values())
    counts["final"] = len(cands)
    return RetrievalResult(config=config, query=query, candidates=cands, timings_ms=timings, stage_counts=counts)
