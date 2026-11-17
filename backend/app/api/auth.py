from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserRole
from app.services.audit import audit
from app.services.serializers import user_out

router = APIRouter(tags=["auth"])

_failed: dict[str, int] = {}  # naive in-memory brute-force throttle per username


class LoginIn(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    full_name: str = ""
    password: str = Field(min_length=8)
    role: UserRole = UserRole.investigator


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    if _failed.get(body.username, 0) >= 10:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts; restart the server or contact admin")
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        _failed[body.username] = _failed.get(body.username, 0) + 1
        audit(db, None, "login_failed", "user", None, username=body.username)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    _failed.pop(body.username, None)
    audit(db, user, "login", "user", user.id)
    db.commit()
    return {"access_token": create_access_token(str(user.id), user.role.value), "token_type": "bearer", "user": user_out(user)}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.get("/users/directory")
def user_directory(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Minimal list (no roles) for assigning case members."""
    return [{"id": str(u.id), "username": u.username, "full_name": u.full_name}
            for u in db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username))]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "Username already exists")
    u = User(username=body.username, full_name=body.full_name, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.flush()
    audit(db, admin, "user_created", "user", u.id, role=body.role.value)
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        if u.id == admin.id and not body.is_active:
            raise HTTPException(400, "You cannot deactivate your own account")
        u.is_active = body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
    audit(db, admin, "user_updated", "user", u.id)
    db.commit()
    return user_out(u)
