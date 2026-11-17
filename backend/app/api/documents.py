from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_or_query_token, require_writer
from app.ingestion.worker import enqueue
from app.models import Case, Document, DocumentChunk, DocumentStatus, DocumentType, ExtractedEntity, LegalDocument, User, UserRole
from app.services import viewer
from app.services.access import accessible_documents_filter, can_access_case, can_modify_document, get_document_or_404
from app.services.audit import audit
from app.services.serializers import document_out, entity_out
from app.services.storage import UploadRejected, safe_filename, store_upload

router = APIRouter(prefix="/documents", tags=["documents"])


def _parse_date(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(422, f"Invalid date '{v}', expected YYYY-MM-DD")


@router.post("/upload", status_code=201)
async def upload_documents(
    files: list[UploadFile] = File(...),
    doc_type: DocumentType = Form(DocumentType.OTHER),
    case_id: uuid.UUID | None = Form(None),
    title: str | None = Form(None),
    incident_date: str | None = Form(None),
    police_station: str | None = Form(None),
    district: str | None = Form(None),
    language: str | None = Form(None),
    classification: str = Form("restricted"),
    # Legal source provenance (only for doc_type = Legal Document; admin only)
    act_name: str | None = Form(None),
    short_name: str | None = Form(None),
    act_year: int | None = Form(None),
    version: str | None = Form(None),
    effective_date: str | None = Form(None),
    source_url: str | None = Form(None),
    publication: str | None = Form(None),
    is_official_text: bool = Form(False),
    verified_by: str | None = Form(None),
    verification_date: str | None = Form(None),
    is_historical: bool = Form(False),
    replaced_by: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_writer),
):
    if case_id is not None:
        case = db.get(Case, case_id)
        if case is None or not can_access_case(db, user, case):
            raise HTTPException(404, "Case not found")
    if doc_type == DocumentType.LEGAL_DOCUMENT and user.role != UserRole.admin:
        raise HTTPException(403, "Only administrators can add legal reference sources")
    results = []
    for f in files:
        data = await f.read()
        name = safe_filename(f.filename or "document")
        try:
            stored = store_upload(name, data)
        except UploadRejected as e:
            results.append({"filename": name, "error": str(e)})
            continue
        existing = db.scalar(select(Document).where(Document.sha256 == stored.sha256))
        if existing is not None:
            visible = db.scalar(select(Document.id).where(Document.id == existing.id, accessible_documents_filter(user)))
            results.append({"filename": name, "duplicate": True,
                            "document": document_out(existing) if visible else None,
                            "error": None if visible else "An identical file already exists in a case you cannot access"})
            continue
        doc = Document(
            title=(title if title and len(files) == 1 else name.rsplit(".", 1)[0])[:300], original_filename=name,
            stored_path=str(stored.path), mime_type=stored.mime, file_ext=stored.ext, sha256=stored.sha256,
            size_bytes=stored.size, doc_type=doc_type, case_id=case_id, uploaded_by=user.id,
            incident_date=_parse_date(incident_date), police_station=police_station, district=district,
            language=language, classification=classification, status=DocumentStatus.uploaded, metadata_json={},
        )
        db.add(doc)
        db.flush()
        if doc_type == DocumentType.LEGAL_DOCUMENT:
            db.add(LegalDocument(
                document_id=doc.id, act_name=act_name or doc.title, short_name=(short_name or "").upper() or None,
                year=act_year, version=version, effective_date=_parse_date(effective_date), source_url=source_url,
                publication=publication, is_official_text=is_official_text, verified_by=verified_by,
                verification_date=_parse_date(verification_date), is_historical=is_historical, replaced_by=replaced_by))
        audit(db, user, "document_uploaded", "document", doc.id, sha256=stored.sha256, doc_type=doc_type.value)
        db.commit()
        enqueue(doc.id)
        results.append({"filename": name, "duplicate": False, "document": document_out(doc)})
    return {"results": results}


@router.get("")
def list_documents(
    q: str | None = None, status: DocumentStatus | None = None, doc_type: DocumentType | None = None,
    case_id: uuid.UUID | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    stmt = select(Document, Case.case_number).outerjoin(Case, Case.id == Document.case_id).where(accessible_documents_filter(user))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.title.ilike(like), Document.original_filename.ilike(like),
                              Document.police_station.ilike(like), Case.case_number.ilike(like)))
    if status:
        stmt = stmt.where(Document.status == status)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if case_id:
        stmt = stmt.where(Document.case_id == case_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [document_out(d, cn) for d, cn in rows]}


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = get_document_or_404(db, user, document_id)
    case_number = db.scalar(select(Case.case_number).where(Case.id == doc.case_id)) if doc.case_id else None
    out = document_out(doc, case_number)
    out["can_modify"] = can_modify_document(user, doc, db)
    audit(db, user, "document_viewed", "document", doc.id)
    db.commit()
    return out


class DocumentPatch(BaseModel):
    title: str | None = None
    doc_type: DocumentType | None = None
    case_id: uuid.UUID | None = None
    clear_case: bool = False
    incident_date: date | None = None
    police_station: str | None = None
    district: str | None = None
    language: str | None = None
    classification: str | None = None


@router.patch("/{document_id}")
def update_document(document_id: uuid.UUID, body: DocumentPatch, db: Session = Depends(get_db),
                    user: User = Depends(require_writer)):
    doc = get_document_or_404(db, user, document_id)
    if not can_modify_document(user, doc, db):
        raise HTTPException(403, "You cannot modify this document")
    data = body.model_dump(exclude_unset=True)
    if body.clear_case:
        doc.case_id = None
    elif "case_id" in data and body.case_id:
        case = db.get(Case, body.case_id)
        if case is None or not can_access_case(db, user, case):
            raise HTTPException(404, "Case not found")
        doc.case_id = case.id
    for k in ("title", "doc_type", "incident_date", "police_station", "district", "language", "classification"):
        if k in data and data[k] is not None:
            setattr(doc, k, data[k])
    audit(db, user, "document_metadata_updated", "document", doc.id, fields=sorted(k for k in data if k != "clear_case"))
    db.commit()
    return document_out(doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    doc = get_document_or_404(db, user, document_id)
    if not can_modify_document(user, doc, db):
        raise HTTPException(403, "You cannot delete this document")
    path = doc.stored_path
    import shutil
    from pathlib import Path

    from app.ingestion.pipeline import processed_dir_for

    processed = processed_dir_for(doc.id)
    db.delete(doc)  # chunks, embeddings, entities and legal metadata cascade
    audit(db, user, "document_deleted", "document", document_id, sha256=doc.sha256)
    db.commit()
    Path(path).unlink(missing_ok=True)
    shutil.rmtree(processed, ignore_errors=True)
    return Response(status_code=204)


@router.post("/{document_id}/reprocess")
def reprocess(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    doc = get_document_or_404(db, user, document_id)
    if not can_modify_document(user, doc, db):
        raise HTTPException(403, "You cannot reprocess this document")
    doc.status, doc.status_detail, doc.error_message = DocumentStatus.uploaded, "Queued for reprocessing", None
    audit(db, user, "document_reprocessed", "document", doc.id)
    db.commit()
    enqueue(doc.id)
    return document_out(doc)


@router.get("/{document_id}/file")
def download_file(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user_or_query_token)):
    doc = get_document_or_404(db, user, document_id)
    audit(db, user, "document_file_opened", "document", doc.id)
    db.commit()
    return FileResponse(doc.stored_path, media_type=doc.mime_type, filename=doc.original_filename,
                        content_disposition_type="inline")


@router.get("/{document_id}/chunks")
def list_chunks(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = get_document_or_404(db, user, document_id)
    rows = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index))
    return [{"id": str(c.id), "chunk_index": c.chunk_index, "page_start": c.page_start, "page_end": c.page_end,
             "heading": c.heading, "section_number": c.section_number, "token_count": c.token_count, "text": c.text}
            for c in rows]


@router.get("/{document_id}/pages/{page}/image")
def page_image(document_id: uuid.UUID, page: int, passage: str | None = None, chunk_id: uuid.UUID | None = None,
               db: Session = Depends(get_db), user: User = Depends(get_current_user_or_query_token)):
    doc = get_document_or_404(db, user, document_id)
    if chunk_id and not passage:
        ch = db.get(DocumentChunk, chunk_id)
        if ch and ch.document_id == doc.id:
            passage = ch.text[:400]
    try:
        png, hits = viewer.render_page_png(doc, page, passage)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except IndexError:
        raise HTTPException(404, "Page out of range")
    return Response(png, media_type="image/png", headers={"X-Highlight-Count": str(hits), "Cache-Control": "private, max-age=60"})


@router.get("/{document_id}/pages/{page}/text")
def page_text(document_id: uuid.UUID, page: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = get_document_or_404(db, user, document_id)
    try:
        return {"page": page, "page_count": doc.page_count, "text": viewer.page_text(doc, page)}
    except IndexError:
        raise HTTPException(404, "Page out of range")


@router.get("/{document_id}/entities")
def document_entities(document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = get_document_or_404(db, user, document_id)
    rows = db.scalars(select(ExtractedEntity).where(ExtractedEntity.document_id == doc.id)
                      .order_by(ExtractedEntity.entity_type, ExtractedEntity.page))
    return [entity_out(e, doc.title) for e in rows]
