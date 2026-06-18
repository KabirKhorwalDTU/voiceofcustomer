from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from typing import Optional

from fastapi import Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserSession


SESSION_DAYS = 30
GUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{12,80}$")


@dataclass
class Actor:
    user_id: Optional[str] = None
    guest_id: Optional[str] = None
    is_operator: bool = False

    @property
    def is_authenticated(self) -> bool:
        return bool(self.user_id)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def clean_guest_id(value: str = "") -> str:
    value = value.strip()
    return value if GUEST_ID_RE.match(value) else ""


def actor_from_headers(authorization: str = Header(default=""), x_guest_id: str = Header(default="")) -> Actor:
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    return Actor(user_id=None, guest_id=clean_guest_id(x_guest_id) or None), token


def resolve_actor(session: Session, authorization: str = "", guest_id: str = "", operator_mode: str = "") -> Actor:
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    actor = Actor(guest_id=clean_guest_id(guest_id) or None, is_operator=operator_mode.lower() == "true")
    if not token:
        return actor
    token_hash = hash_token(token)
    row = session.execute(
        select(UserSession).where(UserSession.token_hash == token_hash, UserSession.expires_at > datetime.now(timezone.utc))
    ).scalars().first()
    if row:
        actor.user_id = row.user_id
    return actor


def create_or_get_user(session: Session, email: str) -> User:
    normalized = normalize_email(email)
    user = session.execute(select(User).where(User.email == normalized)).scalars().first()
    if user is None:
        user = User(email=normalized, display_name=normalized.split("@")[0])
        session.add(user)
        session.flush()
    else:
        user.last_seen_at = datetime.now(timezone.utc)
    return user


def create_user_session(session: Session, user: User) -> tuple[str, UserSession]:
    raw_token = secrets.token_urlsafe(32)
    row = UserSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    )
    session.add(row)
    session.flush()
    return raw_token, row
