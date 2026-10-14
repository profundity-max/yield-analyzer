from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User, UserSession

password_hash = PasswordHash.recommended()
settings = get_settings()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def create_session(db: Session, user: User) -> tuple[UserSession, str]:
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    now = utcnow_naive()
    session = UserSession(
        token_hash=sha256(raw_token),
        csrf_token=csrf_token,
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=settings.session_max_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, raw_token


def get_session_by_token(db: Session, raw_token: str) -> UserSession | None:
    session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == sha256(raw_token),
            UserSession.revoked_at.is_(None),
        )
    )
    if session is None:
        return None
    now = utcnow_naive()
    expires_at = session.expires_at.replace(tzinfo=None)
    last_seen_at = session.last_seen_at.replace(tzinfo=None)
    if expires_at < now or last_seen_at + timedelta(minutes=settings.session_idle_minutes) < now:
        session.revoked_at = now
        db.commit()
        return None
    session.last_seen_at = now
    db.commit()
    return session


def revoke_session(db: Session, session: UserSession) -> None:
    session.revoked_at = utcnow_naive()
    db.commit()


def register_failure(db: Session, user: User) -> None:
    user.failed_attempts += 1
    if user.failed_attempts >= settings.login_max_failures:
        user.locked_until = utcnow_naive() + timedelta(minutes=settings.login_lock_minutes)
    db.commit()


def register_success(db: Session, user: User) -> None:
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
