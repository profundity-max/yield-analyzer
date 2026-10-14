from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import current_session, require_csrf
from app.models import AuditLog, User
from app.schemas import ChangePasswordRequest, LoginRequest, SessionView, UserView
from app.security import (
    create_session,
    hash_password,
    register_failure,
    register_success,
    revoke_session,
    utcnow_naive,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/login", response_model=SessionView)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> SessionView:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    now = utcnow_naive()
    if user.locked_until and user.locked_until.replace(tzinfo=None) > now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="账号暂时锁定")
    if not verify_password(payload.password, user.password_hash):
        register_failure(db, user)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    register_success(db, user)
    session, raw_token = create_session(db, user)
    response.set_cookie(
        "aim_session",
        raw_token,
        max_age=settings.session_max_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="login",
            entity_type="user",
            entity_id=user.id,
            detail_json="{}",
        )
    )
    db.commit()
    return SessionView(user=UserView.model_validate(user), csrf_token=session.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    identity=Depends(current_session),
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    _, session = identity
    revoke_session(db, session)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="logout",
            entity_type="user",
            entity_id=user.id,
            detail_json="{}",
        )
    )
    db.commit()
    response.delete_cookie("aim_session", path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=SessionView)
def me(identity=Depends(current_session)) -> SessionView:
    user, session = identity
    return SessionView(user=UserView.model_validate(user), csrf_token=session.csrf_token)


@router.post("/change-password", response_model=UserView)
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> UserView:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="change_password",
            entity_type="user",
            entity_id=user.id,
            detail_json="{}",
        )
    )
    db.commit()
    return UserView.model_validate(user)
