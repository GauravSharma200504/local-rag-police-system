"""Dashboard statistics, settings, model status, audit logs and evaluation endpoints."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_DIR
from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.models import AuditLog, Case, Document, DocumentChunk, QueryLog, Report, User, UserRole
from app.services import model_status
from app.services.access import accessible_documents_filter, member_case_ids
from app.services.audit import audit
from app.services.jobs import submit
from app.services.runtime_settings import load_params, save_params

router = APIRouter(tags=["system"])
RESULTS_DIR = PROJECT_DIR / "evaluation" / "results"


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docf = accessible_documents_filter(user)
    total_docs = db.scalar(select(func.count(Document.id)).where(docf))
    total_chunks = db.scalar(select(func.count(DocumentChunk.id)).join(Document).where(docf))
    case_q = select(func.count(Case.id))
    if user.role != UserRole.admin:
        case_q = case_q.where(or_(Case.created_by == user.id, Case.id.in_(member_case_ids(user))))
    total_cases = db.scalar(case_q)
    q_scope = QueryLog.user_id == user.id if user.role != UserRole.admin else QueryLog.id.isnot(None)
    total_queries = db.scalar(select(func.count(QueryLog.id)).where(q_scope))
    status_counts = dict(db.execute(select(Document.status, func.count()).where(docf).group_by(Document.status)).all())
    type_counts = dict(db.execute(select(Document.doc_type, func.count()).where(docf).group_by(Document.doc_type)).all())
    lang_counts = dict(db.execute(select(Document.language, func.count()).where(docf).group_by(Document.language)).all())
    recent = db.scalars(select(Document).where(docf).order_by(Document.created_at.desc()).limit(6)).all()
    activity = db.scalars(select(QueryLog).where(q_scope).order_by(QueryLog.created_at.desc()).limit(8)).all()
    since = datetime.now(timezone.utc) - timedelta(days=13)
    day = func.date_trunc("day", Document.created_at)
    trend = db.execute(select(day, func.count()).where(docf, Document.created_at >= since).group_by(day).order_by(day)).all()
    lat = db.execute(select(func.avg(QueryLog.total_ms), func.avg(QueryLog.retrieval_ms))
                     .where(q_scope, QueryLog.query_type == "chat")).one()
    avg_proc = db.scalar(select(func.avg(Document.processing_seconds)).where(docf, Document.status == "indexed"))
    reports = db.scalar(select(func.count(Report.id)).where(Report.created_by == user.id) if user.role != UserRole.admin
                        else select(func.count(Report.id)))
    return {
        "totals": {"documents": total_docs, "chunks": total_chunks, "cases": total_cases, "queries": total_queries,
                   "reports": reports, "ocr_documents": db.scalar(select(func.count(Document.id)).where(docf, func.jsonb_array_length(Document.ocr_pages) > 0))},
        "status_counts": {k.value if hasattr(k, "value") else k: v for k, v in status_counts.items()},
        "type_counts": {k.value if hasattr(k, "value") else k: v for k, v in type_counts.items()},
        "language_counts": {(k or "unknown"): v for k, v in lang_counts.items()},
        "recent_documents": [{"id": str(d.id), "title": d.title, "doc_type": d.doc_type.value, "status": d.status.value,
                              "created_at": d.created_at.isoformat()} for d in recent],
        "recent_activity": [{"type": a.query_type, "config": a.retrieval_config, "results": a.num_results,
                             "abstained": a.abstained, "total_ms": round(a.total_ms or 0, 1),
                             "created_at": a.created_at.isoformat()} for a in activity],
        "ingestion_trend": [{"date": d.date().isoformat(), "count": c} for d, c in trend],
        "performance": {"avg_answer_ms": round(lat[0], 1) if lat[0] else None,
                        "avg_retrieval_ms": round(lat[1], 1) if lat[1] else None,
                        "avg_processing_seconds": round(avg_proc, 2) if avg_proc else None},
    }


@router.get("/settings/models")
def models(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return model_status.component_status(load_params(db).ollama_model)


@router.post("/settings/models/test/{component}")
def test_component(component: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if component == "embedding":
        return model_status.test_embedder()
    if component == "reranker":
        return model_status.test_reranker()
    if component == "llm":
        return model_status.test_llm(load_params(db).ollama_model)
    raise HTTPException(404, "Unknown component")


class ParamsIn(BaseModel):
    retrieval_top_k: int | None = Field(default=None, ge=1, le=200)
    rerank_top_k: int | None = Field(default=None, ge=1, le=20)
    dense_similarity_threshold: float | None = Field(default=None, ge=-1, le=1)
    rerank_score_threshold: float | None = Field(default=None, ge=-50, le=50)
    rrf_k: int | None = Field(default=None, ge=1, le=1000)
    citation_support_threshold: float | None = Field(default=None, ge=0, le=1)
    ollama_model: str | None = Field(default=None, min_length=1, max_length=200)
    llm_temperature: float | None = Field(default=None, ge=0, le=2)


@router.get("/settings/retrieval")
def get_params(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return load_params(db).to_dict()


@router.put("/settings/retrieval")
def put_params(body: ParamsIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = save_params(db, body.model_dump(exclude_none=True))
    audit(db, admin, "settings_updated", "settings", "retrieval", **body.model_dump(exclude_none=True))
    db.commit()
    return p.to_dict()


@router.get("/audit-logs")
def audit_logs(limit: int = 200, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.execute(select(AuditLog, User.username).outerjoin(User, User.id == AuditLog.user_id)
                      .order_by(AuditLog.created_at.desc()).limit(min(limit, 1000))).all()
    return [{"id": str(a.id), "username": u, "action": a.action, "target_type": a.target_type, "target_id": a.target_id,
             "detail": a.detail, "created_at": a.created_at.isoformat()} for a, u in rows]


# ------------------------------------------------------------------ evaluation
_eval_state: dict = {"running": False, "log": [], "error": None}


@router.get("/evaluation/results")
def evaluation_results(_: User = Depends(get_current_user)):
    f = RESULTS_DIR / "latest.json"
    return {"state": {k: v for k, v in _eval_state.items() if k != "log"}, "log": _eval_state["log"][-30:],
            "results": json.loads(f.read_text(encoding="utf-8")) if f.exists() else None}


class EvalIn(BaseModel):
    configs: list[str] = Field(default_factory=lambda: ["vector", "hybrid", "proposed"])
    generation: bool = True
    limit: int | None = None


@router.post("/evaluation/run", status_code=202)
def run_evaluation(body: EvalIn, admin: User = Depends(require_admin)):
    if _eval_state["running"]:
        raise HTTPException(409, "An evaluation is already running")
    for c in body.configs:
        if c not in ("vector", "hybrid", "proposed"):
            raise HTTPException(422, f"Unknown config {c}")

    def job():
        import sys

        sys.path.insert(0, str(PROJECT_DIR))
        from evaluation.scripts.run_evaluation import run

        _eval_state.update(running=True, log=[], error=None)
        try:
            run(configs=body.configs, generation=body.generation, limit=body.limit, log=_eval_state["log"].append)
        except Exception as e:  # noqa: BLE001
            _eval_state["error"] = f"{type(e).__name__}: {e}"
        finally:
            _eval_state["running"] = False

    submit(job)
    return {"started": True}
