"""Shared, permission-scoped base query for chunk retrieval.

Access control is applied here, inside SQL, so dense and sparse retrieval can only ever
rank chunks from documents the user is authorized to read.
"""
from __future__ import annotations

from sqlalchemy import Select, select

from app.models import Document, DocumentChunk, DocumentStatus, DocumentType, User
from app.retrieval.types import Candidate, RetrievalFilters
from app.services.access import accessible_documents_filter

CHUNK_COLUMNS = (
    DocumentChunk.id, DocumentChunk.document_id, Document.title, Document.original_filename, Document.doc_type,
    Document.case_id, DocumentChunk.page_start, DocumentChunk.page_end, DocumentChunk.page_spans,
    DocumentChunk.heading, DocumentChunk.section_number, DocumentChunk.text,
)


def scoped_select(user: User, filters: RetrievalFilters, *extra_columns) -> Select:
    q = (
        select(*CHUNK_COLUMNS, *extra_columns)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(accessible_documents_filter(user), Document.status == DocumentStatus.indexed)
    )
    if filters.case_id is not None:
        q = q.where(Document.case_id == filters.case_id)
    if filters.document_ids:
        q = q.where(Document.id.in_(filters.document_ids))
    if filters.doc_types:
        q = q.where(Document.doc_type.in_([DocumentType(t) for t in filters.doc_types]))
    if filters.legal_only:
        q = q.where(Document.doc_type == DocumentType.LEGAL_DOCUMENT)
    if filters.exclude_legal:
        q = q.where(Document.doc_type != DocumentType.LEGAL_DOCUMENT)
    return q


def row_to_candidate(row) -> Candidate:
    return Candidate(
        chunk_id=row[0], document_id=row[1], document_title=row[2], filename=row[3],
        doc_type=row[4].value if hasattr(row[4], "value") else str(row[4]), case_id=row[5],
        page_start=row[6], page_end=row[7], page_spans=row[8] or [], heading=row[9],
        section_number=row[10], text=row[11],
    )
