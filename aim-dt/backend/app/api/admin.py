from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user, require_role
from app.models import AuditLog, MappingVersion, SpecVersion, User
from app.schemas import (
    MappingCreate,
    MappingView,
    SpecCreate,
    SpecView,
    UserCreate,
    UserUpdate,
    UserView,
)
from app.security import hash_password
from app.services.rules import canonical_json, fingerprint

router = APIRouter(prefix="/admin", tags=["admin"])


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def audit(
    db: Session, actor: User, action: str, entity_type: str, entity_id: str, detail: dict
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail_json=canonical_json(detail),
        )
    )


@router.get("/specs", response_model=list[SpecView])
def list_specs(
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SpecView]:
    items = db.scalars(select(SpecVersion).order_by(SpecVersion.created_at.desc())).all()
    return [SpecView.model_validate(item) for item in items]


@router.post("/specs", response_model=SpecView)
def create_spec(
    payload: SpecCreate,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> SpecView:
    raw = payload.model_dump(mode="json")
    digest = fingerprint(raw)
    existing = db.scalar(select(SpecVersion).where(SpecVersion.fingerprint == digest))
    if existing is not None:
        return SpecView.model_validate(existing)
    spec = SpecVersion(
        name=payload.name,
        fingerprint=digest,
        status="draft",
        enabled_points_json=canonical_json(payload.enabled_points),
        rules_json=canonical_json(payload.rules.model_dump()),
        source_batch_id=payload.source_batch_id,
        created_by=user.id,
    )
    db.add(spec)
    audit(db, user, "create_spec", "spec", spec.id, raw)
    db.commit()
    db.refresh(spec)
    return SpecView.model_validate(spec)


@router.post("/specs/{spec_id}/confirm", response_model=SpecView)
def confirm_spec(
    spec_id: str,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> SpecView:
    spec = db.get(SpecVersion, spec_id)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规格不存在")
    old_status = spec.status
    spec.status = "active"
    spec.confirmed_by = user.id
    spec.confirmed_at = utcnow_naive()
    for other in db.scalars(
        select(SpecVersion).where(SpecVersion.id != spec.id, SpecVersion.status == "active")
    ):
        other.status = "retired"
    audit(db, user, "confirm_spec", "spec", spec.id, {"from": old_status, "to": "active"})
    db.commit()
    db.refresh(spec)
    return SpecView.model_validate(spec)


@router.get("/mappings", response_model=list[MappingView])
def list_mappings(
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[MappingView]:
    items = db.scalars(select(MappingVersion).order_by(MappingVersion.created_at.desc())).all()
    return [MappingView.model_validate(item) for item in items]


@router.post("/mappings", response_model=MappingView)
def create_mapping(
    payload: MappingCreate,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> MappingView:
    raw = [item.model_dump(mode="json") for item in payload.rules]
    digest = fingerprint(raw)
    existing = db.scalar(select(MappingVersion).where(MappingVersion.fingerprint == digest))
    if existing is not None:
        return MappingView.model_validate(existing)
    mapping = MappingVersion(
        name=payload.name,
        fingerprint=digest,
        status="active",
        rules_json=canonical_json(raw),
        created_by=user.id,
        confirmed_by=user.id,
        confirmed_at=utcnow_naive(),
    )
    for other in db.scalars(select(MappingVersion).where(MappingVersion.status == "active")):
        other.status = "retired"
    db.add(mapping)
    audit(db, user, "create_mapping", "mapping", mapping.id, {"rules": raw})
    db.commit()
    db.refresh(mapping)
    return MappingView.model_validate(mapping)


@router.get("/users", response_model=list[UserView])
def list_users(
    _user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> list[UserView]:
    return [
        UserView.model_validate(item)
        for item in db.scalars(select(User).order_by(User.username)).all()
    ]


@router.post("/users", response_model=UserView)
def create_user(
    payload: UserCreate,
    actor: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> UserView:
    if db.scalar(select(User).where(User.username == payload.username)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        must_change_password=True,
    )
    db.add(user)
    audit(db, actor, "create_user", "user", user.id, {"username": user.username, "role": user.role})
    db.commit()
    db.refresh(user)
    return UserView.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserView)
def update_user(
    user_id: str,
    payload: UserUpdate,
    actor: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> UserView:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    changes: dict = {}
    if payload.role is not None:
        changes["role"] = {"from": user.role, "to": payload.role}
        user.role = payload.role
    if payload.is_active is not None:
        changes["is_active"] = {"from": user.is_active, "to": payload.is_active}
        user.is_active = payload.is_active
    audit(db, actor, "update_user", "user", user.id, changes)
    db.commit()
    db.refresh(user)
    return UserView.model_validate(user)


@router.get("/audit-logs")
def list_audit_logs(
    limit: int = 200,
    _user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    safe_limit = min(max(limit, 1), 1000)
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(safe_limit)).all()
    return {
        "items": [
            {
                "id": row.id,
                "actor_user_id": row.actor_user_id,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "detail": json.loads(row.detail_json),
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }
