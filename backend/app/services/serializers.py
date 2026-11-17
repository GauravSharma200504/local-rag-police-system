"""Explicit response shaping: internal ORM objects are never returned directly from the API."""
from __future__ import annotations

from app.models import Case, Conversation, Document, ExtractedEntity, Message, Report, User


def user_out(u: User) -> dict:
    return {"id": str(u.id), "username": u.username, "full_name": u.full_name, "role": u.role.value,
            "is_active": u.is_active, "created_at": u.created_at.isoformat() if u.created_at else None}


def document_out(d: Document, case_number: str | None = None) -> dict:
    return {
        "id": str(d.id), "title": d.title, "original_filename": d.original_filename, "file_ext": d.file_ext,
        "mime_type": d.mime_type, "size_bytes": d.size_bytes, "sha256": d.sha256, "doc_type": d.doc_type.value,
        "case_id": str(d.case_id) if d.case_id else None, "case_number": case_number,
        "incident_date": d.incident_date.isoformat() if d.incident_date else None,
        "police_station": d.police_station, "district": d.district, "language": d.language,
        "classification": d.classification, "page_count": d.page_count, "ocr_pages": d.ocr_pages or [],
        "status": d.status.value, "status_detail": d.status_detail, "error_message": d.error_message,
        "processing_seconds": d.processing_seconds, "chunk_count": d.chunk_count, "embedding_model": d.embedding_model,
        "metadata": d.metadata_json or {}, "uploaded_by": str(d.uploaded_by) if d.uploaded_by else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def case_out(c: Case, doc_count: int | None = None) -> dict:
    return {"id": str(c.id), "case_number": c.case_number, "title": c.title, "description": c.description,
            "police_station": c.police_station, "district": c.district, "status": c.status,
            "created_by": str(c.created_by) if c.created_by else None, "document_count": doc_count,
            "created_at": c.created_at.isoformat() if c.created_at else None}


def entity_out(e: ExtractedEntity, title: str | None = None) -> dict:
    return {"id": str(e.id), "document_id": str(e.document_id), "document_title": title, "entity_type": e.entity_type,
            "value": e.value, "normalized_value": e.normalized_value, "page": e.page, "context": e.context,
            "method": e.method, "confidence": e.confidence, "verification_status": e.verification_status,
            "chunk_id": str(e.chunk_id) if e.chunk_id else None}


def message_out(m: Message) -> dict:
    return {
        "id": str(m.id), "role": m.role, "content": m.content, "abstained": m.abstained,
        "retrieval": m.retrieval_meta or {}, "created_at": m.created_at.isoformat() if m.created_at else None,
        "citations": [{"label": c.label, "chunk_id": str(c.chunk_id) if c.chunk_id else None,
                       "document_id": str(c.document_id) if c.document_id else None, "document_title": c.document_title,
                       "page": c.page, "passage": c.passage, "support": c.support_score, "verified": c.verified}
                      for c in sorted(m.citations, key=lambda c: int(c.label[1:]) if c.label[1:].isdigit() else 0)],
    }


def conversation_out(c: Conversation, with_messages: bool = False) -> dict:
    out = {"id": str(c.id), "title": c.title, "case_id": str(c.case_id) if c.case_id else None,
           "created_at": c.created_at.isoformat() if c.created_at else None,
           "updated_at": c.updated_at.isoformat() if c.updated_at else None}
    if with_messages:
        out["messages"] = [message_out(m) for m in c.messages]
    return out


def report_out(r: Report, with_content: bool = False) -> dict:
    out = {"id": str(r.id), "report_type": r.report_type, "title": r.title, "status": r.status,
           "case_id": str(r.case_id) if r.case_id else None,
           "created_at": r.created_at.isoformat() if r.created_at else None,
           "updated_at": r.updated_at.isoformat() if r.updated_at else None,
           "progress": (r.content or {}).get("progress"), "error": (r.content or {}).get("error")}
    if with_content:
        out["content"] = r.content
    return out
