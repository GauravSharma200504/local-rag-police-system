from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class RetrievalFilters:
    case_id: uuid.UUID | None = None
    document_ids: list[uuid.UUID] | None = None
    doc_types: list[str] | None = None
    legal_only: bool = False
    exclude_legal: bool = False


@dataclass
class Candidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    filename: str
    doc_type: str
    case_id: uuid.UUID | None
    page_start: int
    page_end: int
    page_spans: list
    heading: str | None
    section_number: str | None
    text: str
    scores: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chunk_id": str(self.chunk_id), "document_id": str(self.document_id),
            "document_title": self.document_title, "filename": self.filename, "doc_type": self.doc_type,
            "page_start": self.page_start, "page_end": self.page_end, "heading": self.heading,
            "section_number": self.section_number, "text": self.text,
            "scores": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in self.scores.items()},
        }


@dataclass
class RetrievalResult:
    config: str
    query: str
    candidates: list[Candidate]
    timings_ms: dict = field(default_factory=dict)
    stage_counts: dict = field(default_factory=dict)
