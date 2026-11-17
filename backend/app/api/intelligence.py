from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_writer
from app.intelligence.comparison import llm_comparison, structured_comparison
from app.intelligence.export import report_to_blocks, to_docx, to_pdf
from app.intelligence.legal import legal_documents, legal_search
from app.intelligence.timeline import build_timeline
from app.models import ExtractedEntity, LegalDocument, QueryLog, Report, User, UserRole
from app.services.access import can_access_case, get_document_or_404
from app.services.audit import audit
from app.services.runtime_settings import load_params
from app.services.serializers import entity_out, report_out

router = APIRouter(tags=["intelligence"])


class CompareIn(BaseModel):
    document_a: uuid.UUID
    document_b: uuid.UUID
    narrative: bool = False
    save: bool = True


class TimelineIn(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1)


class EntityPatch(BaseModel):
    value: str | None = None
    verification_status: str | None = Field(default=None, pattern="^(unverified|verified|rejected)$")


class LegalSearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    act: str | None = None
    explain: bool = False
    top_k: int = Field(default=5, ge=1, le=20)


class LegalPatch(BaseModel):
    act_name: str | None = None
    short_name: str | None = None
    version: str | None = None
    source_url: str | None = None
    publication: str | None = None
    is_official_text: bool | None = None
    verified_by: str | None = None
    is_historical: bool | None = None
    replaced_by: str | None = None


@router.post("/intelligence/compare")
def compare(body: CompareIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.document_a == body.document_b:
        raise HTTPException(422, "Select two different documents")
    a = get_document_or_404(db, user, body.document_a)
    b = get_document_or_404(db, user, body.document_b)
    content = {"a": {"id": str(a.id), "title": a.title, "doc_type": a.doc_type.value},
               "b": {"id": str(b.id), "title": b.title, "doc_type": b.doc_type.value},
               "structured": structured_comparison(db, a, b),
               "disclaimer": "AI-assisted comparison draft. The system does not determine which statement is correct."}
    if body.narrative:
        content["narrative"] = llm_comparison(db, user, a, b, load_params(db))
    out = {"content": content}
    if body.save:
        r = Report(report_type="comparison", title=f"Comparison: {a.title} vs {b.title}", case_id=a.case_id if a.case_id == b.case_id else None,
                   created_by=user.id, content=content, status="draft")
        db.add(r)
        db.flush()
        out["report"] = report_out(r)
    db.add(QueryLog(user_id=user.id, query_type="compare", retrieval_config="structured", num_results=2))
    audit(db, user, "documents_compared", "document", a.id, other=str(b.id))
    db.commit()
    return out


@router.post("/intelligence/timeline")
def timeline(body: TimelineIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ids = [get_document_or_404(db, user, d).id for d in body.document_ids]
    return build_timeline(db, ids)


@router.patch("/entities/{entity_id}")
def update_entity(entity_id: uuid.UUID, body: EntityPatch, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    e = db.get(ExtractedEntity, entity_id)
    if e is None:
        raise HTTPException(404, "Entity not found")
    doc = get_document_or_404(db, user, e.document_id)
    if body.value is not None:
        e.value = body.value
        e.normalized_value = body.value.lower().strip()
        e.method = "human_corrected"
    if body.verification_status:
        e.verification_status = body.verification_status
    audit(db, user, "entity_reviewed", "entity", e.id, status=e.verification_status)
    db.commit()
    return entity_out(e, doc.title)


# ------------------------------------------------------------------ legal
@router.post("/legal/search")
def search_legal(body: LegalSearchIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    res = legal_search(db, user, body.query, load_params(db), body.act, body.explain, body.top_k)
    db.add(QueryLog(user_id=user.id, query_type="legal", retrieval_config="proposed", num_results=len(res["results"]),
                    abstained=not res["results"]))
    audit(db, user, "legal_search", None, None, explain=body.explain)
    db.commit()
    return res


@router.get("/legal/sources")
def list_legal_sources(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return legal_documents(db)


@router.patch("/legal/sources/{document_id}")
def update_legal_source(document_id: uuid.UUID, body: LegalPatch, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    if user.role != UserRole.admin:
        raise HTTPException(403, "Only administrators can edit legal source provenance")
    ld = db.scalar(select(LegalDocument).where(LegalDocument.document_id == document_id))
    if ld is None:
        raise HTTPException(404, "Legal source not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ld, k, v.upper() if k == "short_name" and v else v)
    audit(db, user, "legal_source_updated", "document", document_id)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ reports
def _report_or_404(db: Session, user: User, rid: uuid.UUID) -> Report:
    r = db.get(Report, rid)
    if r is None:
        raise HTTPException(404, "Report not found")
    if user.role != UserRole.admin and r.created_by != user.id:
        if r.case_id is None:
            raise HTTPException(404, "Report not found")
        from app.models import Case

        case = db.get(Case, r.case_id)
        if case is None or not can_access_case(db, user, case):
            raise HTTPException(404, "Report not found")
    return r


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Report).order_by(Report.created_at.desc())
    rows = db.scalars(stmt).all()
    visible = []
    for r in rows:
        try:
            _report_or_404(db, user, r.id)
            visible.append(report_out(r))
        except HTTPException:
            continue
    return visible


@router.get("/reports/{rid}")
def get_report(rid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return report_out(_report_or_404(db, user, rid), with_content=True)


class ReportPatch(BaseModel):
    status: str = Field(pattern="^(draft|human_verified)$")


@router.patch("/reports/{rid}")
def update_report(rid: uuid.UUID, body: ReportPatch, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    r = _report_or_404(db, user, rid)
    if r.status in ("generating", "failed"):
        raise HTTPException(409, "Report is not ready")
    r.status = body.status
    audit(db, user, "report_status_changed", "report", r.id, status=body.status)
    db.commit()
    return report_out(r)


@router.delete("/reports/{rid}", status_code=204)
def delete_report(rid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    r = _report_or_404(db, user, rid)
    db.delete(r)
    audit(db, user, "report_deleted", "report", rid)
    db.commit()
    return Response(status_code=204)


@router.get("/reports/{rid}/export")
def export_report(rid: uuid.UUID, format: str = "pdf", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _report_or_404(db, user, rid)
    if r.status in ("generating", "failed"):
        raise HTTPException(409, "Report is not ready")
    blocks = report_to_blocks(r.report_type, r.title, r.content or {}, r.status)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in r.title)[:80]
    audit(db, user, "report_exported", "report", r.id, format=format)
    db.commit()
    if format == "docx":
        return Response(to_docx(blocks), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.docx"'})
    if format == "pdf":
        return Response(to_pdf(blocks), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'})
    raise HTTPException(422, "format must be pdf or docx")

