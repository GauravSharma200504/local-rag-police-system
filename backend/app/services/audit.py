"""Audit trail helper. Never logs document contents, only identifiers and operation metadata."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(db: Session, user: User | None, action: str, target_type: str | None = None,
          target_id: str | None = None, **detail) -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, target_type=target_type,
                    target_id=str(target_id) if target_id else None, detail=detail))
