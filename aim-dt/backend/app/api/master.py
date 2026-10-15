from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user, require_role
from app.models import AuditLog, Batch, DataModule, User
from app.schemas import AnalysisView, BatchView, MasterWorkbench
from app.services.master import (
    active_batches,
    create_master_analysis,
    master_workbench,
    revert_module,
)
from app.services.rules import canonical_json
from app.services.storage import new_batch_id, save_upload

router = APIRouter(prefix="/master", tags=["master"])


def _cleanup_rejected_file(stored_path: Path) -> None:
    if stored_path.exists():
        stored_path.unlink()
    parent = stored_path.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


@router.get("/workbench", response_model=MasterWorkbench)
def get_master_workbench(
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MasterWorkbench:
    return MasterWorkbench.model_validate(master_workbench(db))


@router.post("/refresh", response_model=AnalysisView, status_code=status.HTTP_202_ACCEPTED)
def refresh_master(
    user: User = Depends(require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> AnalysisView:
    if not active_batches(db):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="总数据源没有可用模块")
    run = create_master_analysis(
        db,
        trigger="manual_refresh",
        requested_by=user.id,
    )
    return AnalysisView.model_validate(run)


@router.post(
    "/modules/{module_id}/replace",
    response_model=BatchView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replace_module_file(
    module_id: str,
    file: UploadFile = File(...),
    user: User = Depends(require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> BatchView:
    module = db.get(DataModule, module_id)
    if module is None or not module.active_batch_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据模块不存在")
    old = db.get(Batch, module.active_batch_id)
    if old is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前模块版本不存在")
    if not file.filename or Path(file.filename).suffix.lower() not in {".xlsx", ".csv"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 XLSX 或 CSV")
    batch_id = new_batch_id()
    try:
        stored_path, size, file_hash = await save_upload(file, batch_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    if file_hash == old.file_sha256:
        _cleanup_rejected_file(stored_path)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="替换文件与当前版本相同")
    existing = db.scalar(select(Batch).where(Batch.file_sha256 == file_hash))
    if existing is not None:
        _cleanup_rejected_file(stored_path)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该文件已在其他模块中存在")
    max_revision = (
        db.scalar(select(func.max(Batch.revision)).where(Batch.data_module_id == module.id))
        or old.revision
    )
    batch = Batch(
        id=batch_id,
        original_name=file.filename,
        stored_path=str(stored_path),
        parquet_path=str(Path(stored_path).parents[1].parent / "parquet" / f"{batch_id}.parquet"),
        file_format=Path(file.filename).suffix.lower().lstrip("."),
        file_size=size,
        file_sha256=file_hash,
        status="replacement_pending",
        data_module_id=module.id,
        revision=max_revision + 1,
        is_active=False,
        replaced_from_batch_id=old.id,
        created_by=user.id,
    )
    db.add(batch)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="replace_module_file",
            entity_type="data_module",
            entity_id=module.id,
            detail_json=canonical_json(
                {"module_id": module.id, "from_batch_id": old.id, "to_batch_id": batch.id}
            ),
        )
    )
    db.commit()
    db.refresh(batch)
    return BatchView.model_validate(batch)


@router.post(
    "/modules/{module_id}/revert",
    response_model=AnalysisView,
    status_code=status.HTTP_202_ACCEPTED,
)
def revert_module_file(
    module_id: str,
    user: User = Depends(require_role("admin", "analyst")),
    db: Session = Depends(get_db),
) -> AnalysisView:
    try:
        run = revert_module(db, module_id=module_id, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AnalysisView.model_validate(run)
