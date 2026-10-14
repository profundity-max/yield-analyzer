from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user, require_role
from app.models import AuditLog, Batch, User
from app.schemas import BatchView
from app.services.rules import canonical_json
from app.services.storage import new_batch_id, save_upload

router = APIRouter(prefix="/batches", tags=["batches"])


@router.get("", response_model=list[BatchView])
def list_batches(
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[BatchView]:
    items = db.scalars(select(Batch).order_by(Batch.created_at.desc())).all()
    return [BatchView.model_validate(item) for item in items]


@router.get("/{batch_id}", response_model=BatchView)
def get_batch(
    batch_id: str,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> BatchView:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="批次不存在")
    return BatchView.model_validate(batch)


@router.post("", response_model=BatchView, status_code=status.HTTP_202_ACCEPTED)
async def upload_batch(
    file: UploadFile = File(...),
    user: User = Depends(require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> BatchView:
    if not file.filename or Path(file.filename).suffix.lower() not in {".xlsx", ".csv"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 XLSX 或 CSV")
    batch_id = new_batch_id()
    try:
        stored_path, size, file_hash = await save_upload(file, batch_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    existing = db.scalar(select(Batch).where(Batch.file_sha256 == file_hash))
    if existing is not None:
        for path in [Path(stored_path), Path(stored_path).parent]:
            if path.is_dir():
                path.rmdir()
            elif path.exists():
                path.unlink()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该文件已上传")
    batch = Batch(
        id=batch_id,
        original_name=file.filename,
        stored_path=str(stored_path),
        parquet_path=str(Path(stored_path).parents[1].parent / "parquet" / f"{batch_id}.parquet"),
        file_format=Path(file.filename).suffix.lower().lstrip("."),
        file_size=size,
        file_sha256=file_hash,
        created_by=user.id,
    )
    db.add(batch)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="upload_batch",
            entity_type="batch",
            entity_id=batch.id,
            detail_json=canonical_json({"filename": file.filename, "size": size}),
        )
    )
    db.commit()
    db.refresh(batch)
    return BatchView.model_validate(batch)


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_batch(
    batch_id: str,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> None:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="批次不存在")
    for value in (batch.parquet_path, batch.stored_path):
        if value:
            path = Path(value)
            if path.exists():
                path.unlink()
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="delete_batch",
            entity_type="batch",
            entity_id=batch.id,
            detail_json=canonical_json({"filename": batch.original_name}),
        )
    )
    db.delete(batch)
    db.commit()
