"""FastAPI dependencies: current user and role guards."""
from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User, UserRole

bearer = HTTPBearer(auto_error=False)


def _user_from_token(token: str, db: Session) -> User:
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return _user_from_token(creds.credentials, db)


def get_current_user_or_query_token(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    token: str | None = Query(default=None, description="Token for <img>/<a> resource URLs"),
    db: Session = Depends(get_db),
) -> User:
    """Allows ?token= for resources loaded by the browser directly (page images, file downloads)."""
    if creds is not None:
        return _user_from_token(creds.credentials, db)
    if token:
        return _user_from_token(token, db)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


def require_roles(*roles: UserRole):
    def guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions for this operation")
        return user

    return guard


require_admin = require_roles(UserRole.admin)
require_writer = require_roles(UserRole.admin, UserRole.investigator)
