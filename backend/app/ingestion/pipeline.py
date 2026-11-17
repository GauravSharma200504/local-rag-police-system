"""Document ingestion pipeline: extract → OCR → clean → chunk → embed → store/index → entities.

The pipeline is idempotent: re-running it for a document replaces that document's chunks and
entities inside one transaction, so a document is never left half-indexed.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion import cleaner
from app.ingestion.chunker import chunk_blocks
from app.ingestion.embeddings import get_embedder
from app.ingestion.extractors import Block, ExtractionError, extract
from app.intelligence.entities import extract_entities, page_for_offset
from app.models import Document, DocumentChunk, DocumentStatus, DocumentType, ExtractedEntity

log = logging.getLogger("bpi.ingestion")


def processed_dir_for(document_id: uuid.UUID) -> Path:
    return get_settings().processed_dir / str(document_id)


def _set_status(db: Session, doc: Document, status: DocumentStatus, detail: str | None = None):
    doc.status = status
    doc.status_detail = detail
    db.commit()


def process_document(db: Session, document_id: uuid.UUID) -> Document:
    settings = get_settings()
    doc = db.get(Document, document_id)
    if doc is None:
        raise ValueError(f"Document {document_id} not found")
    t0 = time.perf_counter()
    doc.error_message = None
    try:
        _set_status(db, doc, DocumentStatus.extracting, "Extracting text")

        def progress(stage: str, detail: str):
            if stage == "ocr" and doc.status != DocumentStatus.ocr:
                _set_status(db, doc, DocumentStatus.ocr, detail)

        result = extract(Path(doc.stored_path), doc.file_ext, processed_dir_for(doc.id), progress)
        blocks: list[Block] = []
        for page in result.pages:
            for b in page.blocks:
                text = cleaner.clean_paragraph(b.text)
                if text:
                    blocks.append(Block(text=text, page=b.page, is_heading=b.is_heading))
        if not blocks:
            reason = "No text could be extracted"
            if result.ocr_failed_pages:
                reason += " (scanned pages found but OCR is unavailable: install Tesseract)"
            raise ExtractionError(reason)

        full_text = "\n\n".join(b.text for b in blocks)
        doc.page_count = result.page_count
        doc.ocr_pages = result.ocr_pages
        doc.language = doc.language or cleaner.detect_language(full_text)
        meta = dict(doc.metadata_json or {})
        meta["extraction_warnings"] = result.warnings
        meta["ocr_failed_pages"] = result.ocr_failed_pages
        doc.metadata_json = meta

        _set_status(db, doc, DocumentStatus.chunking, f"Chunking {len(blocks)} paragraphs")
        chunks = chunk_blocks(blocks, settings.chunk_size_tokens, settings.chunk_overlap_tokens,
                              legal=doc.doc_type == DocumentType.LEGAL_DOCUMENT)

        _set_status(db, doc, DocumentStatus.embedding, f"Embedding {len(chunks)} chunks")
        embedder = get_embedder()
        vectors: list[list[float]] = []
        bs = settings.embedding_batch_size
        for i in range(0, len(chunks), bs):
            batch = chunks[i:i + bs]
            texts = [(f"{c.heading}\n{c.text}" if c.heading and not c.text.startswith(c.heading) else c.text) for c in batch]
            vectors.extend(embedder.embed_documents(texts))

        # Replace existing chunks/entities atomically (idempotent re-processing)
        db.execute(delete(ExtractedEntity).where(ExtractedEntity.document_id == doc.id))
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        rows = []
        for idx, (c, vec) in enumerate(zip(chunks, vectors, strict=True)):
            row = DocumentChunk(
                id=uuid.uuid4(), document_id=doc.id, chunk_index=idx, text=c.text,
                page_start=c.page_start, page_end=c.page_end, page_spans=c.page_spans,
                heading=c.heading, section_number=c.section_number, token_count=c.token_count,
                embedding=vec, embedding_model=embedder.name,
            )
            db.add(row)
            rows.append((row, c))
        db.flush()  # chunks must exist before entities reference them

        seen_entities: set[tuple] = set()
        for row, c in rows:
            for e in extract_entities(c.text):
                key = (e.entity_type, e.normalized, e.context)
                if key in seen_entities:
                    continue  # same mention repeated in the chunk-overlap region
                seen_entities.add(key)
                db.add(ExtractedEntity(
                    document_id=doc.id, chunk_id=row.id, entity_type=e.entity_type, value=e.value[:500],
                    normalized_value=e.normalized[:500], page=page_for_offset(c.page_spans, e.start, c.page_start),
                    span_start=e.start, span_end=e.end, context=e.context, method="rule", confidence=e.confidence,
                ))
        doc.chunk_count = len(chunks)
        doc.embedding_model = embedder.name
        doc.processing_seconds = round(time.perf_counter() - t0, 3)
        doc.status = DocumentStatus.indexed
        doc.status_detail = f"Indexed {len(chunks)} chunks" + (f", OCR on {len(result.ocr_pages)} page(s)" if result.ocr_pages else "")
        db.commit()
        log.info("indexed document %s (%d chunks, %.2fs)", doc.id, len(chunks), doc.processing_seconds)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        doc = db.get(Document, document_id)
        doc.status = DocumentStatus.failed
        doc.error_message = f"{type(e).__name__}: {e}"[:2000]
        doc.processing_seconds = round(time.perf_counter() - t0, 3)
        db.commit()
        log.warning("ingestion failed for %s: %s", document_id, e)
    return doc
