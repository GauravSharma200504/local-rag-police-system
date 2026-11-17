"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.api import auth, cases, chat, documents, intelligence, system
from app.core.config import get_settings
from app.core.database import SessionLocal, get_engine
from app.models import Document, DocumentStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bpi")


def _recover_interrupted_jobs():
    """Documents left mid-pipeline by a restart are marked failed so they can be reprocessed explicitly."""
    db = SessionLocal()
    try:
        stuck = db.scalars(select(Document).where(Document.status.in_(
            [DocumentStatus.extracting, DocumentStatus.ocr, DocumentStatus.chunking, DocumentStatus.embedding,
             DocumentStatus.uploaded]))).all()
        for d in stuck:
            d.status, d.error_message = DocumentStatus.failed, "Processing was interrupted by a server restart. Click Reprocess."
        db.commit()
        if stuck:
            log.warning("marked %d interrupted document(s) as failed", len(stuck))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        _recover_interrupted_jobs()
    except Exception as e:  # noqa: BLE001
        log.error("Database not reachable at startup: %s", e)
    yield


settings = get_settings()
app = FastAPI(title="Bharat Police Intelligence API", version="1.0.0", lifespan=lifespan,
              description="Local-first, evidence-grounded police document intelligence (academic decision-support system).")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Highlight-Count", "Content-Disposition"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error. See server logs."})


api = APIRouter(prefix="/api/v1")
for module in (auth, documents, cases, chat, intelligence, system):
    api.include_router(module.router)
app.include_router(api)


@app.get("/health")
def health():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            vec = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
        return {"status": "ok", "database": "ok", "pgvector": vec}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "degraded", "database": str(e)[:200]})
