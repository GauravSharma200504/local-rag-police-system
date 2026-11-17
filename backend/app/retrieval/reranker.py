"""Cross-encoder reranking (local). Scores each (query, passage) pair jointly."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import get_settings
from app.retrieval.types import Candidate


class RerankerError(Exception):
    pass


class Reranker(ABC):
    name: str

    @abstractmethod
    def score(self, query: str, passages: list[str]) -> list[float]: ...

    def rerank(self, query: str, cands: list[Candidate], top_k: int, min_score: float | None = None) -> list[Candidate]:
        if not cands:
            return []
        scores = self.score(query, [c.text for c in cands])
        for c, s in zip(cands, scores, strict=True):
            c.scores["rerank"] = float(s)
        ranked = sorted(cands, key=lambda c: c.scores["rerank"], reverse=True)
        if min_score is not None:
            ranked = [c for c in ranked if c.scores["rerank"] >= min_score]
        for i, c in enumerate(ranked, start=1):
            c.scores["rerank_rank"] = i
        return ranked[:top_k]


class CrossEncoderReranker(Reranker):
    def __init__(self, model_name: str, device: str = "cpu", max_length: int = 512):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as e:
            raise RerankerError("sentence-transformers is not installed (pip install -r requirements-ml.txt)") from e
        try:
            self.model = CrossEncoder(model_name, device=device, max_length=max_length)
        except Exception as e:  # noqa: BLE001
            raise RerankerError(f"Could not load reranker '{model_name}'. Run `python -m app.cli download-models`. {e}") from e
        self.name = model_name
        self._lock = threading.Lock()

    def score(self, query, passages):
        with self._lock:
            return [float(s) for s in self.model.predict([(query, p) for p in passages], show_progress_bar=False)]


class PassthroughReranker(Reranker):
    """Keeps fusion order (used when RERANKER_PROVIDER=none). Score = negative fused rank."""

    name = "none"

    def score(self, query, passages):
        return [-float(i) for i in range(len(passages))]


@lru_cache
def get_reranker() -> Reranker:
    s = get_settings()
    if s.reranker_provider.lower() == "cross_encoder":
        return CrossEncoderReranker(s.reranker_model, s.embedding_device)
    if s.reranker_provider.lower() == "none":
        return PassthroughReranker()
    raise RerankerError(f"Unknown RERANKER_PROVIDER '{s.reranker_provider}'")
