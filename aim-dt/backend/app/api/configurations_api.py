from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user, require_role
from app.models import AuditLog, Batch, Category, MappingVersion, SpecVersion, User
from app.schemas import (
    CategoryCreate,
    CategoryUpdate,
    CategoryView,
    MappingEditorPayload,
    MappingEditorView,
    SpecEditorPayload,
    SpecEditorView,
)
from app.services.configurations import (
    categories_by_kind,
    create_active_mapping,
    create_active_spec,
    mapping_editor_view,
    spec_to_editor,
)
from app.services.master import active_batches, create_master_analysis
from app.services.rules import canonical_json

router = APIRouter(tags=["configuration"])


def _batch(db: Session, batch_id: str | None) -> Batch | None:
    if not batch_id:
        return None
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="批次不存在")
    return batch


def _active_spec(db: Session) -> SpecVersion | None:
    return db.scalar(select(SpecVersion).where(SpecVersion.status == "active").limit(1))


def _active_mapping(db: Session) -> MappingVersion | None:
    return db.scalar(select(MappingVersion).where(MappingVersion.status == "active").limit(1))


def _category_view(item: Category) -> CategoryView:
    return CategoryView.model_validate(item)


@router.get("/config/options")
def config_options(
    batch_id: str | None = None,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    batch = _batch(db, batch_id)
    spec = _active_spec(db)
    mapping = _active_mapping(db)
    specs = db.scalars(select(SpecVersion).order_by(SpecVersion.created_at.desc())).all()
    mappings = db.scalars(select(MappingVersion).order_by(MappingVersion.created_at.desc())).all()
    categories = categories_by_kind(db)
    return {
        "active_spec_id": spec.id if spec else None,
        "active_mapping_id": mapping.id if mapping else None,
        "specs": [
            {"id": item.id, "name": item.name, "status": item.status, "created_at": item.created_at}
            for item in specs
        ],
        "mappings": [
            {"id": item.id, "name": item.name, "status": item.status, "created_at": item.created_at}
            for item in mappings
        ],
        "points": spec_to_editor(spec, batch)["points"] if spec else [],
        "categories": {
            kind: [_category_view(item) for item in values] for kind, values in categories.items()
        },
    }


@router.get("/specs/editor", response_model=SpecEditorView)
def get_spec_editor(
    spec_id: str | None = None,
    batch_id: str | None = None,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SpecEditorView:
    batch = _batch(db, batch_id)
    spec = db.get(SpecVersion, spec_id) if spec_id else _active_spec(db)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规格不存在")
    return SpecEditorView.model_validate(spec_to_editor(spec, batch))


@router.post("/specs/editor", response_model=SpecEditorView)
def save_spec_editor(
    payload: SpecEditorPayload,
    user: User = Depends(require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> SpecEditorView:
    if not any(point.enabled for point in payload.points):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少启用一个测试点")
    spec = create_active_spec(
        db,
        name=payload.name,
        points=[item.model_dump(mode="json") for item in payload.points],
        user=user,
        source_batch_id=payload.source_batch_id,
    )
    if active_batches(db):
        create_master_analysis(db, trigger="spec_change", requested_by=user.id)
    return SpecEditorView.model_validate(spec_to_editor(spec, _batch(db, payload.source_batch_id)))


@router.get("/mapping-editor", response_model=MappingEditorView)
def get_mapping_editor(
    batch_id: str | None = None,
    mapping_version_id: str | None = None,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MappingEditorView:
    batches = [_batch(db, batch_id)] if batch_id else active_batches(db)
    batches = [item for item in batches if item is not None]
    if not batches:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="总数据源没有可用模块")
    mapping = (
        db.get(MappingVersion, mapping_version_id) if mapping_version_id else _active_mapping(db)
    )
    return MappingEditorView.model_validate(
        mapping_editor_view(db, batches=batches, mapping=mapping)
    )


@router.post("/mappings/editor", response_model=MappingEditorView)
def save_mapping_editor(
    payload: MappingEditorPayload,
    user: User = Depends(require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> MappingEditorView:
    rows = [item.model_dump(mode="json") for item in payload.rows]
    mapping = create_active_mapping(db, name=payload.name, rows=rows, user=user)
    batches = active_batches(db)
    if payload.batch_id:
        selected = _batch(db, payload.batch_id)
        if selected is not None:
            batches = [selected]
    if not batches:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="总数据源没有可用模块")
    create_master_analysis(db, trigger="mapping_change", requested_by=user.id)
    return MappingEditorView.model_validate(
        mapping_editor_view(db, batches=batches, mapping=mapping)
    )


@router.get("/categories", response_model=list[CategoryView])
def list_categories(
    include_inactive: bool = True,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[CategoryView]:
    values = [
        item
        for items in categories_by_kind(db, include_inactive=include_inactive).values()
        for item in items
    ]
    return [_category_view(item) for item in values]


@router.post("/categories", response_model=CategoryView)
def create_category(
    payload: CategoryCreate,
    user: User = Depends(require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> CategoryView:
    existing = db.scalar(
        select(Category).where(Category.kind == payload.kind, Category.code == payload.code)
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="类别代码已存在")
    item = Category(**payload.model_dump())
    db.add(item)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="create_category",
            entity_type="category",
            entity_id=item.id,
            detail_json=canonical_json(payload.model_dump()),
        )
    )
    db.commit()
    db.refresh(item)
    return _category_view(item)


@router.patch("/categories/{category_id}", response_model=CategoryView)
def update_category(
    category_id: str,
    payload: CategoryUpdate,
    user: User = Depends(require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> CategoryView:
    item = db.get(Category, category_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="类别不存在")
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(item, key, value)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="update_category",
            entity_type="category",
            entity_id=item.id,
            detail_json=canonical_json(changes),
        )
    )
    db.commit()
    db.refresh(item)
    return _category_view(item)
