from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession
from app.security import get_session_by_token

settings = get_settings()


def current_session(
    request: Request,
    db: Session = Depends(get_db),
) -> tuple[User, UserSession]:
    raw_token = request.cookies.get("aim_session")
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    session = get_session_by_token(db, raw_token)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    return user, session


def current_user(identity: tuple[User, UserSession] = Depends(current_session)) -> User:
    return identity[0]


def require_csrf(
    x_csrf_token: str | None = Header(default=None),
    identity: tuple[User, UserSession] = Depends(current_session),
) -> User:
    _, session = identity
    if not x_csrf_token or x_csrf_token != session.csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")
    return identity[0]


def require_role(*roles: str) -> Callable[..., User]:
    def dependency(user: User = Depends(require_csrf)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return dependency
