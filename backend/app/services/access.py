"""Document-level access control.

Rule set (enforced in SQL *before* retrieval so unauthorized chunks never reach ranking or the LLM):
- admin: every document.
- other users: documents they uploaded, documents in cases they are a member of,
  and legal reference documents (doc_type = Legal Document), which are shared reference material.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models import Case, CaseMember, Document, DocumentType, User, UserRole


def member_case_ids(user: User) -> Select:
    return select(CaseMember.case_id).where(CaseMember.user_id == user.id)


def accessible_documents_filter(user: User):
    """SQLAlchemy boolean clause restricting Document rows to those the user may read."""
    if user.role == UserRole.admin:
        return Document.id.isnot(None)
    return or_(
        Document.uploaded_by == user.id,
        Document.case_id.in_(member_case_ids(user)),
        Document.doc_type == DocumentType.LEGAL_DOCUMENT,
    )


def accessible_document_ids(user: User) -> Select:
    return select(Document.id).where(accessible_documents_filter(user))


def can_access_case(db: Session, user: User, case: Case) -> bool:
    if user.role == UserRole.admin or case.created_by == user.id:
        return True
    return db.scalar(
        select(CaseMember.id).where(CaseMember.case_id == case.id, CaseMember.user_id == user.id)
    ) is not None


def get_document_or_404(db: Session, user: User, document_id: uuid.UUID) -> Document:
    doc = db.scalar(select(Document).where(Document.id == document_id, accessible_documents_filter(user)))
    if doc is None:
        # Same response for "missing" and "forbidden" so document existence is not leaked.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


def get_case_or_404(db: Session, user: User, case_id: uuid.UUID) -> Case:
    case = db.get(Case, case_id)
    if case is None or not can_access_case(db, user, case):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


def can_modify_document(user: User, doc: Document, db: Session) -> bool:
    if user.role == UserRole.admin:
        return True
    if user.role != UserRole.investigator:
        return False
    if doc.uploaded_by == user.id:
        return True
    return doc.case_id is not None and db.scalar(
        select(CaseMember.id).where(CaseMember.case_id == doc.case_id, CaseMember.user_id == user.id)
    ) is not None
