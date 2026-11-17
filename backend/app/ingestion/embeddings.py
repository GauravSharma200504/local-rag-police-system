"""Local embedding providers.

- sentence_transformers (default): e.g. intfloat/multilingual-e5-small (384-d, Hindi + English).
- ollama: embedding models served by a local Ollama (e.g. nomic-embed-text, bge-m3).
- hashing: deterministic character n-gram feature hashing. It needs no model download and exists
  for automated tests and offline smoke tests only; it is NOT a semantic model and the UI labels it so.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
from abc import ABC, abstractmethod
from functools import lru_cache

import httpx

from app.core.config import get_settings


class EmbeddingError(Exception):
    pass


class Embedder(ABC):
    name: str
    dim: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...


def _l2(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model_name: str, dim: int, device: str = "cpu", batch_size: int = 16):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise EmbeddingError("sentence-transformers is not installed (pip install -r requirements-ml.txt)") from e
        try:
            self.model = SentenceTransformer(model_name, device=device)
        except Exception as e:  # noqa: BLE001
            raise EmbeddingError(
                f"Could not load embedding model '{model_name}'. Download it once with "
                f"`python -m app.cli download-models` (needs internet), then it works offline. Error: {e}"
            ) from e
        actual = self.model.get_sentence_embedding_dimension()
        if actual != dim:
            raise EmbeddingError(f"Model '{model_name}' produces {actual}-d vectors but EMBEDDING_DIM={dim}. "
                                 "Change EMBEDDING_DIM and run `python -m app.cli reindex --recreate`.")
        self.name, self.dim, self.batch_size = model_name, dim, batch_size
        self._e5 = "e5" in model_name.lower()
        self._lock = threading.Lock()

    def _enc(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            vecs = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                     show_progress_bar=False, convert_to_numpy=True)
        return [v.tolist() for v in vecs]

    def embed_documents(self, texts):
        return self._enc([("passage: " + t) if self._e5 else t for t in texts])

    def embed_query(self, text):
        return self._enc([("query: " + text) if self._e5 else text])[0]


class OllamaEmbedder(Embedder):
    def __init__(self, model_name: str, dim: int, base_url: str):
        self.name, self.dim, self.base_url = model_name, dim, base_url.rstrip("/")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = httpx.post(f"{self.base_url}/api/embed", json={"model": self.name, "input": texts}, timeout=120)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise EmbeddingError(f"Ollama embedding failed for model '{self.name}': {e}") from e
        vecs = r.json().get("embeddings", [])
        if not vecs or len(vecs[0]) != self.dim:
            raise EmbeddingError(f"Ollama model '{self.name}' returned unexpected dimension; EMBEDDING_DIM={self.dim}")
        return [_l2(v) for v in vecs]

    def embed_documents(self, texts):
        return self._embed(texts)

    def embed_query(self, text):
        return self._embed([text])[0]


class HashingEmbedder(Embedder):
    """Feature-hashing embedder (lexical, not semantic). For tests/offline smoke runs only."""

    _tok = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)

    def __init__(self, dim: int):
        self.name, self.dim = "hashing-test-embedder", dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        words = [w.lower() for w in self._tok.findall(text)]
        feats = words + [f"#{w[i:i + 4]}" for w in words for i in range(max(1, len(w) - 3))]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        return _l2(v)

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


_lock = threading.Lock()


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    with _lock:
        provider = s.embedding_provider.lower()
        if provider == "sentence_transformers":
            return SentenceTransformerEmbedder(s.embedding_model, s.embedding_dim, s.embedding_device, s.embedding_batch_size)
        if provider == "ollama":
            return OllamaEmbedder(s.embedding_model, s.embedding_dim, s.ollama_base_url)
        if provider == "hashing":
            return HashingEmbedder(s.embedding_dim)
        raise EmbeddingError(f"Unknown EMBEDDING_PROVIDER '{s.embedding_provider}'")


def current_embedding_model_name() -> str:
    s = get_settings()
    return "hashing-test-embedder" if s.embedding_provider.lower() == "hashing" else s.embedding_model
