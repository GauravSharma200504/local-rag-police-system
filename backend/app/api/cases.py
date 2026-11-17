from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_writer
from app.intelligence.summary import summary_report_title
from app.intelligence.timeline import build_timeline
from app.models import Case, CaseMember, Document, ExtractedEntity, Report, User, UserRole
from app.services.access import can_access_case, can_modify_document, get_case_or_404, get_document_or_404, member_case_ids
from app.services.audit import audit
from app.services.jobs import submit_summary
from app.services.serializers import case_out, document_out, entity_out, report_out

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseIn(BaseModel):
    case_number: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=300)
    description: str = ""
    police_station: str | None = None
    district: str | None = None
    status: str = "open"


class CasePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    police_station: str | None = None
    district: str | None = None
    status: str | None = None


class MemberIn(BaseModel):
    user_id: uuid.UUID


class AssignDocs(BaseModel):
    document_ids: list[uuid.UUID]


@router.post("", status_code=201)
def create_case(body: CaseIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    if db.scalar(select(Case).where(Case.case_number == body.case_number)):
        raise HTTPException(409, "A case with this number already exists")
    case = Case(**body.model_dump(), created_by=user.id)
    db.add(case)
    db.flush()
    db.add(CaseMember(case_id=case.id, user_id=user.id))
    audit(db, user, "case_created", "case", case.id, case_number=case.case_number)
    db.commit()
    return case_out(case, 0)


@router.get("")
def list_cases(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Case, func.count(Document.id)).outerjoin(Document, Document.case_id == Case.id).group_by(Case.id)
    if user.role != UserRole.admin:
        stmt = stmt.where(or_(Case.created_by == user.id, Case.id.in_(member_case_ids(user))))
    return [case_out(c, n) for c, n in db.execute(stmt.order_by(Case.created_at.desc())).all()]


@router.get("/{case_id}")
def get_case(case_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_case_or_404(db, user, case_id)
    docs = db.scalars(select(Document).where(Document.case_id == case.id).order_by(Document.doc_type, Document.title)).all()
    members = db.execute(select(User).join(CaseMember, CaseMember.user_id == User.id).where(CaseMember.case_id == case.id)).scalars()
    out = case_out(case, len(docs))
    out["documents"] = [document_out(d, case.case_number) for d in docs]
    out["members"] = [{"id": str(m.id), "username": m.username, "full_name": m.full_name, "role": m.role.value} for m in members]
    return out


@router.patch("/{case_id}")
def update_case(case_id: uuid.UUID, body: CasePatch, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    case = get_case_or_404(db, user, case_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(case, k, v)
    audit(db, user, "case_updated", "case", case.id)
    db.commit()
    return case_out(case)


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    case = get_case_or_404(db, user, case_id)
    if user.role != UserRole.admin and case.created_by != user.id:
        raise HTTPException(403, "Only the case creator or an admin can delete a case")
    audit(db, user, "case_deleted", "case", case.id, case_number=case.case_number)
    db.delete(case)  # documents are kept and become unassigned (FK SET NULL)
    db.commit()
    return Response(status_code=204)


@router.post("/{case_id}/members")
def add_member(case_id: uuid.UUID, body: MemberIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    case = get_case_or_404(db, user, case_id)
    if not db.get(User, body.user_id):
        raise HTTPException(404, "User not found")
    if not db.scalar(select(CaseMember).where(CaseMember.case_id == case.id, CaseMember.user_id == body.user_id)):
        db.add(CaseMember(case_id=case.id, user_id=body.user_id))
        audit(db, user, "case_member_added", "case", case.id, member=str(body.user_id))
        db.commit()
    return {"ok": True}


@router.delete("/{case_id}/members/{user_id}")
def remove_member(case_id: uuid.UUID, user_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    case = get_case_or_404(db, user, case_id)
    m = db.scalar(select(CaseMember).where(CaseMember.case_id == case.id, CaseMember.user_id == user_id))
    if m:
        db.delete(m)
        audit(db, user, "case_member_removed", "case", case.id, member=str(user_id))
        db.commit()
    return {"ok": True}


@router.post("/{case_id}/documents")
def assign_documents(case_id: uuid.UUID, body: AssignDocs, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    """Associate documents with a case. Every association is an explicit user action and is audited."""
    case = get_case_or_404(db, user, case_id)
    for doc_id in body.document_ids:
        doc = get_document_or_404(db, user, doc_id)
        if not can_modify_document(user, doc, db):
            raise HTTPException(403, f"You cannot modify document {doc_id}")
        doc.case_id = case.id
        audit(db, user, "document_assigned_to_case", "document", doc.id, case_id=str(case.id))
    db.commit()
    return {"ok": True, "assigned": len(body.document_ids)}


@router.get("/{case_id}/timeline")
def case_timeline(case_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_case_or_404(db, user, case_id)
    ids = list(db.scalars(select(Document.id).where(Document.case_id == case.id)))
    return build_timeline(db, ids)


@router.get("/{case_id}/entities")
def case_entities(case_id: uuid.UUID, entity_type: str | None = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    case = get_case_or_404(db, user, case_id)
    stmt = (select(ExtractedEntity, Document.title).join(Document, Document.id == ExtractedEntity.document_id)
            .where(Document.case_id == case.id))
    if entity_type:
        stmt = stmt.where(ExtractedEntity.entity_type == entity_type)
    rows = db.execute(stmt.order_by(ExtractedEntity.entity_type, ExtractedEntity.normalized_value)).all()
    return [entity_out(e, t) for e, t in rows]


@router.post("/{case_id}/summary", status_code=202)
def create_summary(case_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_case_or_404(db, user, case_id)
    report = Report(report_type="case_summary", title=summary_report_title(case), case_id=case.id, created_by=user.id,
                    status="generating", content={"progress": "Queued"})
    db.add(report)
    audit(db, user, "case_summary_requested", "case", case.id)
    db.commit()
    submit_summary(report.id, case.id, user.id)
    return report_out(report)


def ensure_case_access(db: Session, user: User, case_id: uuid.UUID | None) -> None:
    if case_id is not None:
        case = db.get(Case, case_id)
        if case is None or not can_access_case(db, user, case):
            raise HTTPException(404, "Case not found")
