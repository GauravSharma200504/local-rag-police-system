"""RAG orchestrator: retrieve → build context → local LLM → validate citations → result.

`answer_stream` yields events so the API can stream tokens (SSE) and the evaluator can reuse the
exact same code path non-streaming via `answer`.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import User
from app.rag import citations as cit
from app.rag.llm import LLMUnavailable, OllamaClient, get_llm
from app.rag.prompts import build_context, build_messages
from app.retrieval.pipeline import retrieve
from app.retrieval.types import Candidate, RetrievalFilters, RetrievalResult
from app.services.runtime_settings import RetrievalParams


@dataclass
class AnswerResult:
    answer: str
    abstained: bool
    config: str
    citations: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported_sentences: list[str] = field(default_factory=list)
    raw_answer: str = ""
    retrieval: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)
    llm_error: str | None = None


def citation_dict(c: cit.ValidatedCitation) -> dict:
    return {
        "label": c.label, "chunk_id": str(c.candidate.chunk_id), "document_id": str(c.candidate.document_id),
        "document_title": c.candidate.document_title, "filename": c.candidate.filename,
        "doc_type": c.candidate.doc_type, "page": c.page, "passage": c.passage, "support": c.support,
    }


def source_dict(label: str, c: Candidate) -> dict:
    d = c.to_dict()
    d["label"] = label
    return d


def answer_stream(db: Session, user: User, question: str, params: RetrievalParams, history: list[dict] | None = None,
                  filters: RetrievalFilters | None = None, config: str = "proposed",
                  llm: OllamaClient | None = None, validate_citations: bool | None = None,
                  retrieval_result: RetrievalResult | None = None, **retrieve_kwargs) -> Iterator[tuple[str, object]]:
    settings = get_settings()
    validate_citations = (config == "proposed") if validate_citations is None else validate_citations
    t0 = time.perf_counter()
    rr = retrieval_result or retrieve(db, user, question, params, filters, config, **retrieve_kwargs)
    context, used, warnings = build_context(rr.candidates, max_tokens=max(1000, settings.llm_num_ctx - 1800))
    sources = [source_dict(f"S{i + 1}", c) for i, c in enumerate(used)]
    retrieval_meta = {"config": rr.config, "stage_counts": rr.stage_counts,
                      "timings_ms": {k: round(v, 1) for k, v in rr.timings_ms.items()}}
    yield "sources", {"sources": sources, "retrieval": retrieval_meta, "warnings": warnings}

    result = AnswerResult(answer="", abstained=False, config=config, sources=sources, warnings=list(warnings),
                          retrieval=retrieval_meta)
    if not used:
        result.answer, result.abstained = cit.ABSTAIN_MESSAGE, True
        result.timings_ms = {"retrieval_ms": rr.timings_ms.get("total_ms", 0), "total_ms": (time.perf_counter() - t0) * 1000}
        yield "final", result
        return

    llm = llm or get_llm()
    messages = build_messages(question, context, history or [])
    t_gen = time.perf_counter()
    raw = []
    try:
        for token in llm.chat_stream(params.ollama_model, messages, params.llm_temperature, settings.llm_num_ctx):
            raw.append(token)
            yield "token", token
    except LLMUnavailable as e:
        result.llm_error = str(e)
        result.answer = ("The local language model is unavailable, so no answer was generated. "
                         f"{e} The retrieved evidence is listed in the Evidence panel.")
        result.abstained = True
        result.timings_ms = {"retrieval_ms": rr.timings_ms.get("total_ms", 0), "total_ms": (time.perf_counter() - t0) * 1000}
        yield "final", result
        return
    gen_ms = (time.perf_counter() - t_gen) * 1000
    raw_text = "".join(raw).strip()
    result.raw_answer = raw_text

    if cit.ABSTAIN_TOKEN in raw_text and len(cit.content_words(raw_text.replace(cit.ABSTAIN_TOKEN, ""))) < 4:
        result.answer, result.abstained = cit.ABSTAIN_MESSAGE, True
    elif validate_citations:
        v = cit.validate(raw_text.replace(cit.ABSTAIN_TOKEN, "").strip(), used, params.citation_support_threshold)
        result.warnings += v.warnings
        result.unsupported_sentences = v.unsupported_sentences
        if not v.citations:
            # Nothing in the answer could be tied to evidence: refuse rather than present an ungrounded answer.
            result.answer, result.abstained = cit.ABSTAIN_MESSAGE, True
            result.warnings.append("The generated draft contained no statement verifiable against retrieved sources, so it was withheld.")
        else:
            result.answer = v.text
            result.citations = [citation_dict(c) for c in v.citations]
    else:
        # Baseline configurations: citations are reported as generated, without validation.
        result.answer = raw_text
        by_label = {s["label"]: s for s in sources}
        seen = []
        for m in cit.MARKER.finditer(raw_text):
            for lab in cit._labels(m.group(1)):
                if lab in by_label and lab not in seen:
                    seen.append(lab)
                    s = by_label[lab]
                    result.citations.append({"label": lab, "chunk_id": s["chunk_id"], "document_id": s["document_id"],
                                             "document_title": s["document_title"], "filename": s["filename"],
                                             "doc_type": s["doc_type"], "page": s["page_start"],
                                             "passage": s["text"][:300], "support": None})
    result.timings_ms = {"retrieval_ms": round(rr.timings_ms.get("total_ms", 0), 1), "generation_ms": round(gen_ms, 1),
                         "total_ms": round((time.perf_counter() - t0) * 1000, 1)}
    yield "final", result


def answer(db: Session, user: User, question: str, params: RetrievalParams, **kwargs) -> AnswerResult:
    final = None
    for event, payload in answer_stream(db, user, question, params, **kwargs):
        if event == "final":
            final = payload
    assert final is not None
    return final
