"""Single-worker background queue for ingestion (keeps embedding model memory bounded)."""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import Future, ThreadPoolExecutor

from app.core.database import SessionLocal
from app.ingestion.pipeline import process_document

log = logging.getLogger("bpi.worker")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")


def _run(document_id: uuid.UUID):
    db = SessionLocal()
    try:
        process_document(db, document_id)
    except Exception:  # noqa: BLE001
        log.exception("unexpected ingestion error for %s", document_id)
    finally:
        db.close()


def enqueue(document_id: uuid.UUID) -> Future:
    return _executor.submit(_run, document_id)
