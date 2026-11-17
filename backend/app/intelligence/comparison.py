"""Two-document comparison: common facts, differences, potential conflicts, missing information.

Structured comparison is deterministic (entity based) and every item cites passages from both documents.
An optional LLM narrative is generated with validated [S#] citations. The system never decides which
version is correct.
"""
from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.intelligence.timeline import categorize
from app.models import Document, DocumentChunk, ExtractedEntity, User
from app.rag import citations as cit
from app.rag.engine import citation_dict
from app.rag.llm import LLMUnavailable, get_llm
from app.rag.prompts import SYSTEM_PROMPT, build_context
from app.retrieval.base_query import row_to_candidate, scoped_select
from app.retrieval.types import RetrievalFilters
from app.services.runtime_settings import RetrievalParams

COMPARE_TYPES = ["DATE", "TIME", "LOCATION", "PERSON", "VEHICLE_NUMBER", "PHONE", "AMOUNT", "LEGAL_SECTION",
                 "FIR_NUMBER", "CASE_ID"]
LABELS = {"DATE": "Dates", "TIME": "Times", "LOCATION": "Locations", "PERSON": "People", "VEHICLE_NUMBER": "Vehicle numbers",
          "PHONE": "Phone numbers", "AMOUNT": "Amounts", "LEGAL_SECTION": "Legal sections", "FIR_NUMBER": "FIR numbers",
          "CASE_ID": "Case identifiers"}


def _entity_map(db: Session, doc_id: uuid.UUID) -> dict[str, dict[str, list[dict]]]:
    out: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for e in db.scalars(select(ExtractedEntity).where(ExtractedEntity.document_id == doc_id,
                                                      ExtractedEntity.entity_type.in_(COMPARE_TYPES))):
        out[e.entity_type][e.normalized_value].append({"value": e.value, "page": e.page, "passage": e.context})
    return out


def _ref(doc: Document, mention: dict) -> dict:
    return {"document_id": str(doc.id), "document_title": doc.title, "page": mention["page"], "passage": mention["passage"],
            "value": mention["value"]}


def structured_comparison(db: Session, a: Document, b: Document) -> dict:
    ea, eb = _entity_map(db, a.id), _entity_map(db, b.id)
    common, different, conflicts, missing = [], [], [], []
    for t in COMPARE_TYPES:
        va, vb = ea.get(t, {}), eb.get(t, {})
        for norm in sorted(set(va) & set(vb)):
            common.append({"type": t, "label": LABELS[t], "value": va[norm][0]["value"],
                           "a": _ref(a, va[norm][0]), "b": _ref(b, vb[norm][0])})
        only_a, only_b = sorted(set(va) - set(vb)), sorted(set(vb) - set(va))
        for norm in only_a:
            different.append({"type": t, "label": LABELS[t], "only_in": "a", "value": va[norm][0]["value"], "a": _ref(a, va[norm][0])})
        for norm in only_b:
            different.append({"type": t, "label": LABELS[t], "only_in": "b", "value": vb[norm][0]["value"], "b": _ref(b, vb[norm][0])})
        if va and not vb:
            missing.append({"type": t, "label": LABELS[t], "missing_in": "b",
                            "message": f"{LABELS[t]} are mentioned in '{a.title}' but not in '{b.title}'."})
        if vb and not va:
            missing.append({"type": t, "label": LABELS[t], "missing_in": "a",
                            "message": f"{LABELS[t]} are mentioned in '{b.title}' but not in '{a.title}'."})

    # Potential conflicts: same event category described with different times / dates / vehicles.
    for t in ("TIME", "DATE"):
        cat_a = defaultdict(list)
        cat_b = defaultdict(list)
        for norm, ms in ea.get(t, {}).items():
            for m in ms:
                if (c := categorize(m["passage"])):
                    cat_a[c].append((norm, m))
        for norm, ms in eb.get(t, {}).items():
            for m in ms:
                if (c := categorize(m["passage"])):
                    cat_b[c].append((norm, m))
        for c in set(cat_a) & set(cat_b):
            na, nb = {n for n, _ in cat_a[c]}, {n for n, _ in cat_b[c]}
            if na.isdisjoint(nb):
                conflicts.append({
                    "type": t, "category": c,
                    "message": f"Potentially conflicting {LABELS[t].lower()} for the {c.replace('_', ' ')}: "
                               f"'{a.title}' says {', '.join(sorted(m['value'] for _, m in cat_a[c]))}; "
                               f"'{b.title}' says {', '.join(sorted(m['value'] for _, m in cat_b[c]))}.",
                    "a": [_ref(a, m) for _, m in cat_a[c]], "b": [_ref(b, m) for _, m in cat_b[c]],
                })
    va, vb = ea.get("VEHICLE_NUMBER", {}), eb.get("VEHICLE_NUMBER", {})
    if va and vb and set(va).isdisjoint(vb):
        conflicts.append({
            "type": "VEHICLE_NUMBER", "category": "vehicle",
            "message": f"The documents mention different vehicle registration numbers: "
                       f"{', '.join(m[0]['value'] for m in va.values())} vs {', '.join(m[0]['value'] for m in vb.values())}.",
            "a": [_ref(a, m[0]) for m in va.values()], "b": [_ref(b, m[0]) for m in vb.values()],
        })
    return {"common": common, "different": different, "conflicts": conflicts, "missing": missing}


def llm_comparison(db: Session, user: User, a: Document, b: Document, params: RetrievalParams) -> dict:
    """Narrative comparison generated from both documents' chunks, with validated citations."""
    settings = get_settings()
    rows = db.execute(scoped_select(user, RetrievalFilters(document_ids=[a.id, b.id]))
                      .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)).all()
    cands = [row_to_candidate(r) for r in rows]
    # Interleave A and B so both fit the context budget fairly.
    ca = [c for c in cands if c.document_id == a.id]
    cb = [c for c in cands if c.document_id == b.id]
    mixed = [x for pair in zip(ca, cb) for x in pair] + ca[len(cb):] + cb[len(ca):]
    context, used, warnings = build_context(mixed, max_tokens=max(1000, settings.llm_num_ctx - 1800))
    prompt = (f"SOURCES (untrusted evidence):\n\n{context}\n\nTASK: Compare document A '{a.title}' with document B "
              f"'{b.title}'. Write four short sections: Common facts, Different facts, Potentially conflicting statements, "
              "Information present in only one document. Cite every sentence with [S#]. Do not decide which version is "
              "correct; differences in wording are not contradictions.")
    try:
        raw = get_llm().chat(params.ollama_model, [{"role": "system", "content": SYSTEM_PROMPT},
                                                   {"role": "user", "content": prompt}],
                             params.llm_temperature, settings.llm_num_ctx)
    except LLMUnavailable as e:
        return {"available": False, "error": str(e)}
    v = cit.validate(raw, used, params.citation_support_threshold)
    return {"available": True, "text": v.text, "citations": [citation_dict(c) for c in v.citations],
            "warnings": warnings + v.warnings, "unsupported_sentences": v.unsupported_sentences}
