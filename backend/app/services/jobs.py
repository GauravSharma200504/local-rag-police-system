"""Background jobs for long-running AI tasks (case summaries, evaluation runs)."""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.core.database import SessionLocal
from app.models import Case, Report, User

log = logging.getLogger("bpi.jobs")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-jobs")


def _summary_job(report_id: uuid.UUID, case_id: uuid.UUID, user_id: uuid.UUID):
    from app.intelligence.summary import generate_case_summary
    from app.services.runtime_settings import load_params

    db = SessionLocal()
    try:
        report = db.get(Report, report_id)
        user, case = db.get(User, user_id), db.get(Case, case_id)

        def progress(msg: str):
            report.content = {**(report.content or {}), "progress": msg}
            db.commit()

        content = generate_case_summary(db, user, case, load_params(db), progress)
        report.content = content
        report.status = "draft"
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("summary job failed")
        db.rollback()
        report = db.get(Report, report_id)
        report.status = "failed"
        report.content = {"error": f"{type(e).__name__}: {e}"}
        db.commit()
    finally:
        db.close()


def submit_summary(report_id: uuid.UUID, case_id: uuid.UUID, user_id: uuid.UUID):
    return _executor.submit(_summary_job, report_id, case_id, user_id)


def submit(fn, *args):
    return _executor.submit(fn, *args)
