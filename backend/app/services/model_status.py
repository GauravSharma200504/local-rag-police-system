"""Status/health of local AI components. Never downloads models implicitly."""
from __future__ import annotations

import time

from app.core.config import get_settings
from app.ingestion import ocr
from app.ingestion.embeddings import current_embedding_model_name, get_embedder
from app.rag.llm import OllamaClient
from app.retrieval.reranker import get_reranker


def component_status(ollama_model: str) -> dict:
    s = get_settings()
    langs = ocr.available_languages()
    return {
        "llm": {"runtime": "ollama", "base_url": s.ollama_base_url, **OllamaClient().status(ollama_model)},
        "embedding": {"provider": s.embedding_provider, "model": current_embedding_model_name(), "dim": s.embedding_dim,
                      "device": s.embedding_device, "loaded": get_embedder.cache_info().currsize > 0,
                      "is_test_embedder": s.embedding_provider.lower() == "hashing"},
        "reranker": {"provider": s.reranker_provider, "model": s.reranker_model if s.reranker_provider != "none" else None,
                     "loaded": get_reranker.cache_info().currsize > 0},
        "ocr": {"engine": "tesseract", "version": ocr.tesseract_version(), "languages": list(langs),
                "configured_languages": s.ocr_languages, "available": bool(langs)},
        "chunking": {"chunk_size_tokens": s.chunk_size_tokens, "chunk_overlap_tokens": s.chunk_overlap_tokens},
    }


def test_embedder() -> dict:
    t = time.perf_counter()
    try:
        e = get_embedder()
        v = e.embed_query("FIR robbery jewellery shop / ज्वेलरी दुकान में लूट")
        return {"ok": True, "model": e.name, "dim": len(v), "ms": round((time.perf_counter() - t) * 1000, 1)}
    except Exception as ex:  # noqa: BLE001
        get_embedder.cache_clear()
        return {"ok": False, "error": str(ex)}


def test_reranker() -> dict:
    t = time.perf_counter()
    try:
        r = get_reranker()
        scores = r.score("When was the FIR registered?", ["The FIR was registered at 11:40 PM.", "The weather was clear."])
        return {"ok": True, "model": r.name, "scores": [round(x, 3) for x in scores], "ms": round((time.perf_counter() - t) * 1000, 1)}
    except Exception as ex:  # noqa: BLE001
        get_reranker.cache_clear()
        return {"ok": False, "error": str(ex)}


def test_llm(model: str) -> dict:
    t = time.perf_counter()
    try:
        out = OllamaClient().chat(model, [{"role": "user", "content": "Reply with the single word: ready"}], 0.0, 512)
        return {"ok": True, "model": model, "reply": out.strip()[:100], "ms": round((time.perf_counter() - t) * 1000, 1)}
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "error": str(ex)}
