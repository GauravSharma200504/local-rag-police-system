"""Legal research over uploaded, versioned legal reference documents.

Results always separate (a) the verbatim text of the uploaded source - labelled "official statutory text"
only when an administrator recorded it as an official publication - from (b) optional AI explanations.
If no legal source covers the query, the response says so; no provision is ever generated from model memory.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, LegalDocument, User
from app.rag.engine import answer
from app.retrieval.base_query import row_to_candidate, scoped_select
from app.retrieval.pipeline import retrieve
from app.retrieval.types import RetrievalFilters
from app.services.runtime_settings import RetrievalParams

SECTION_Q = re.compile(r"\b(?:section|sec\.?|s\.|धारा)\s*(\d{1,3}[A-Z]?)", re.I)
ACT_ALIASES = {
    "BNS": ["bns", "bharatiya nyaya sanhita", "nyaya sanhita"],
    "BNSS": ["bnss", "bharatiya nagarik suraksha sanhita", "nagarik suraksha"],
    "BSA": ["bsa", "bharatiya sakshya adhiniyam", "sakshya adhiniyam"],
    "IPC": ["ipc", "indian penal code"],
    "CRPC": ["crpc", "cr.p.c", "code of criminal procedure"],
    "IEA": ["evidence act", "indian evidence act"],
    "COI": ["constitution"],
}


def detect_act(query: str) -> str | None:
    q = query.lower()
    for short in ("BNSS", "BNS", "BSA", "IPC", "CRPC", "IEA", "COI"):  # BNSS before BNS
        for alias in ACT_ALIASES[short]:
            if re.search(rf"\b{re.escape(alias)}\b", q):
                return short
    return None


def legal_meta(ld: LegalDocument | None) -> dict:
    if ld is None:
        return {"act_name": None, "is_official_text": False}
    return {
        "act_name": ld.act_name, "short_name": ld.short_name, "year": ld.year, "version": ld.version,
        "effective_date": ld.effective_date.isoformat() if ld.effective_date else None, "source_url": ld.source_url,
        "publication": ld.publication, "is_official_text": ld.is_official_text, "verified_by": ld.verified_by,
        "verification_date": ld.verification_date.isoformat() if ld.verification_date else None,
        "is_historical": ld.is_historical, "replaced_by": ld.replaced_by,
    }


def legal_search(db: Session, user: User, query: str, params: RetrievalParams, act: str | None = None,
                 explain: bool = False, top_k: int = 5) -> dict:
    explicit_act = act
    act = act or detect_act(query)
    doc_ids = None
    notice = None
    if act:
        doc_ids = list(db.scalars(select(LegalDocument.document_id).where(LegalDocument.short_name.ilike(act)))) or None
        if not doc_ids:
            notice = (f"No legal source for '{act}' has been uploaded, so its provisions cannot be shown. "
                      "Upload the official text in Legal Research.")
            if explicit_act:
                return {"query": query, "act": act, "results": [], "explanation": None, "message": notice}
            notice += " Showing matches from other uploaded legal references instead."
    filters = RetrievalFilters(legal_only=True, document_ids=doc_ids)

    exact = []
    m = SECTION_Q.search(query)
    if m:
        stmt = scoped_select(user, filters).where(DocumentChunk.section_number == m.group(1).upper()).order_by(DocumentChunk.chunk_index)
        exact = [row_to_candidate(r) for r in db.execute(stmt.limit(top_k)).all()]
        for c in exact:
            c.scores["exact_section_match"] = 1.0
    rr = retrieve(db, user, query, params, filters, "proposed", final_k=top_k)
    seen = {c.chunk_id for c in exact}
    merged = exact + [c for c in rr.candidates if c.chunk_id not in seen]
    merged = merged[:top_k]

    meta_by_doc = {ld.document_id: ld for ld in db.scalars(
        select(LegalDocument).where(LegalDocument.document_id.in_([c.document_id for c in merged] or [None])))}
    results = []
    for c in merged:
        lm = legal_meta(meta_by_doc.get(c.document_id))
        results.append({
            **c.to_dict(), "legal": lm,
            "text_label": ("Official statutory text (as uploaded and verified by administrator)" if lm["is_official_text"]
                           else "Reference text - NOT marked as official statutory text"),
        })
    explanation = None
    if explain and merged:
        rr.candidates = merged
        res = answer(db, user, f"Explain, using only the provided legal sources, the following: {query}. "
                               "Quote the operative words of the provision and cite it.", params,
                     filters=filters, config="proposed", retrieval_result=rr)
        explanation = {"label": "AI-generated explanation - not an official legal opinion. Verify against the statutory text.",
                       "text": res.answer, "abstained": res.abstained, "citations": res.citations,
                       "warnings": res.warnings, "llm_error": res.llm_error}
    message = notice or (None if results else "No matching provision was found in the uploaded legal sources.")
    return {"query": query, "act": act, "results": results, "explanation": explanation, "message": message}


def legal_documents(db: Session) -> list[dict]:
    rows = db.execute(select(Document, LegalDocument).join(LegalDocument, LegalDocument.document_id == Document.id)
                      .order_by(LegalDocument.act_name)).all()
    return [{"document_id": str(d.id), "title": d.title, "status": d.status.value, "chunks": d.chunk_count,
             "pages": d.page_count, **legal_meta(ld)} for d, ld in rows]
