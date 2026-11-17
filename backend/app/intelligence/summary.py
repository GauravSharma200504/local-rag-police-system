"""Structured case summary (AI-generated draft requiring human verification).

Sections combine deterministic, entity-derived facts (dates, people, missing information) with
LLM-generated narrative sections, each produced by the proposed RAG pipeline with validated citations.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence.timeline import build_timeline
from app.models import Case, Document, DocumentStatus, DocumentType, ExtractedEntity, User
from app.rag.engine import answer
from app.retrieval.types import RetrievalFilters
from app.services.runtime_settings import RetrievalParams

DISCLAIMER = ("AI-GENERATED DRAFT - requires verification by the investigating officer against the original documents. "
              "This summary does not determine guilt or innocence and is not a legal opinion.")

NARRATIVE_SECTIONS = [
    ("overview", "Case overview", None,
     "Give a brief neutral overview of this case: what is alleged to have happened, where and when, and which documents exist."),
    ("incident_details", "Incident details", None,
     "Describe the incident details (date, time, place, sequence of events, property involved) as recorded in the documents. "
     "Attribute each detail to the document it comes from."),
    ("evidence", "Evidence mentioned", [DocumentType.EVIDENCE_REPORT.value, DocumentType.INVESTIGATION_REPORT.value],
     "List the evidence items mentioned (CCTV, fingerprints, seized items, forensic findings) and their current status."),
    ("investigation_observations", "Investigation observations", [DocumentType.INVESTIGATION_REPORT.value],
     "Summarize the investigating officer's observations and the pending lines of enquiry."),
]


def _section_from_answer(key, title, res) -> dict:
    return {"key": key, "title": title, "text": res.answer, "abstained": res.abstained, "citations": res.citations,
            "warnings": res.warnings, "llm_error": res.llm_error}


def generate_case_summary(db: Session, user: User, case: Case, params: RetrievalParams, progress=None) -> dict:
    docs = db.scalars(select(Document).where(Document.case_id == case.id, Document.status == DocumentStatus.indexed)).all()
    doc_ids = [d.id for d in docs]
    sections = []
    for i, (key, title, types, question) in enumerate(NARRATIVE_SECTIONS):
        if progress:
            progress(f"Generating '{title}' ({i + 1}/{len(NARRATIVE_SECTIONS) + 1})")
        filt = RetrievalFilters(case_id=case.id, doc_types=types, exclude_legal=True)
        res = answer(db, user, question, params, filters=filt, config="proposed", final_k=6)
        sections.append(_section_from_answer(key, title, res))

    witness = []
    for d in [d for d in docs if d.doc_type == DocumentType.WITNESS_STATEMENT]:
        if progress:
            progress(f"Summarizing witness statement {d.title}")
        res = answer(db, user, "Summarize this witness statement: who the witness is, what they say they saw, "
                               "times and descriptions given.", params,
                     filters=RetrievalFilters(document_ids=[d.id]), config="proposed", final_k=4)
        witness.append({"document_id": str(d.id), "document_title": d.title, **_section_from_answer("witness", d.title, res)})

    ents = db.scalars(select(ExtractedEntity).where(ExtractedEntity.document_id.in_(doc_ids))).all() if doc_ids else []
    titles = {d.id: d.title for d in docs}
    people: dict[str, dict] = {}
    places: dict[str, dict] = {}
    for e in ents:
        target = people if e.entity_type == "PERSON" else places if e.entity_type == "LOCATION" else None
        if target is None:
            continue
        item = target.setdefault(e.normalized_value, {"value": e.value, "mentions": 0, "sources": []})
        item["mentions"] += 1
        src = {"document_id": str(e.document_id), "document_title": titles[e.document_id], "page": e.page}
        if src not in item["sources"]:
            item["sources"].append(src)

    timeline = build_timeline(db, doc_ids)
    dates = defaultdict(list)
    for ev in timeline["events"]:
        if ev["date"]:
            dates[ev["date"]].append({"description": ev["description"], "document_title": ev["document_title"],
                                      "page": ev["page"], "nature": ev["nature"], "time": ev["time"]})

    missing = []
    present = {d.doc_type for d in docs}
    for t in (DocumentType.FIR, DocumentType.WITNESS_STATEMENT, DocumentType.INVESTIGATION_REPORT, DocumentType.EVIDENCE_REPORT):
        if t not in present:
            missing.append(f"No {t.value} is available in this case workspace.")
    for c in timeline["conflicts"]:
        missing.append("Unresolved discrepancy: " + c["message"])
    missing += timeline["flags"]
    for s in sections + witness:
        if s["abstained"]:
            missing.append(f"'{s['title']}': sufficient evidence was not found in the case documents.")

    all_citations = []
    for s in sections + witness:
        for c in s["citations"]:
            key = (c["document_id"], c["page"], c["passage"][:80])
            if key not in {(x["document_id"], x["page"], x["passage"][:80]) for x in all_citations}:
                all_citations.append(c)

    return {
        "case_number": case.case_number, "case_title": case.title, "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).isoformat(), "model": params.ollama_model,
        "documents": [{"id": str(d.id), "title": d.title, "doc_type": d.doc_type.value, "pages": d.page_count} for d in docs],
        "sections": sections, "witness_statements": witness,
        "important_dates": [{"date": k, "events": v} for k, v in sorted(dates.items())],
        "people": sorted(people.values(), key=lambda p: -p["mentions"]),
        "locations": sorted(places.values(), key=lambda p: -p["mentions"]),
        "conflicts": timeline["conflicts"], "missing_information": missing, "citations": all_citations,
    }


def summary_report_title(case: Case) -> str:
    return f"Case summary - {case.case_number}"


def as_uuid(x) -> uuid.UUID:
    return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))
