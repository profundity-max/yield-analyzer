from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisRun,
    AuditLog,
    Batch,
    DataModule,
    MappingVersion,
    MasterDataSource,
    RefreshLog,
    SpecVersion,
    User,
)
from app.services.configurations import link_analysis_batches
from app.services.rules import canonical_json


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_master(db: Session, created_by: str | None = None) -> MasterDataSource:
    master = db.scalar(select(MasterDataSource).order_by(MasterDataSource.created_at).limit(1))
    if master is None:
        master = MasterDataSource(name="AIM D-T 总数据源")
        db.add(master)
        db.commit()
        db.refresh(master)
    return master


def active_batches(db: Session) -> list[Batch]:
    return list(
        db.scalars(
            select(Batch)
            .where(Batch.status == "ready", Batch.is_active.is_(True))
            .order_by(Batch.created_at)
        )
    )


def create_master_analysis(
    db: Session,
    *,
    trigger: str,
    requested_by: str,
    module_id: str | None = None,
    from_batch_id: str | None = None,
    to_batch_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AnalysisRun:
    master = ensure_master(db, created_by=requested_by)
    batches = active_batches(db)
    if not batches:
        raise ValueError("总数据源没有可用模块")
    spec = db.scalar(select(SpecVersion).where(SpecVersion.status == "active").limit(1))
    if spec is None:
        raise ValueError("没有 active Spec")
    mapping = db.scalar(select(MappingVersion).where(MappingVersion.status == "active").limit(1))
    run = AnalysisRun(
        name=f"总数据源分析 · {trigger}",
        filters_json=canonical_json({"batch_ids": [item.id for item in batches]}),
        spec_version_id=spec.id,
        mapping_version_id=mapping.id if mapping else None,
        requested_by=requested_by,
    )
    db.add(run)
    db.flush()
    link_analysis_batches(db, run, [item.id for item in batches])
    log = RefreshLog(
        master_source_id=master.id,
        module_id=module_id,
        trigger=trigger,
        status="queued",
        analysis_run_id=run.id,
        from_batch_id=from_batch_id,
        to_batch_id=to_batch_id,
        detail_json=canonical_json(detail or {}),
        requested_by=requested_by,
    )
    db.add(log)
    master.current_analysis_run_id = run.id
    master.updated_at = utcnow_naive()
    db.commit()
    db.refresh(run)
    return run


def record_refresh_failure(db: Session, batch: Batch, error: str) -> None:
    master = ensure_master(db, created_by=batch.created_by)
    if not batch.data_module_id:
        return
    db.add(
        RefreshLog(
            master_source_id=master.id,
            module_id=batch.data_module_id,
            trigger="replace_file" if batch.replaced_from_batch_id else "upload_file",
            status="failed",
            from_batch_id=batch.replaced_from_batch_id,
            to_batch_id=batch.id,
            detail_json=canonical_json({"filename": batch.original_name, "error": error}),
            requested_by=batch.created_by,
            completed_at=utcnow_naive(),
        )
    )
    db.commit()


def complete_refresh_log(db: Session, run: AnalysisRun) -> None:
    log = db.scalar(select(RefreshLog).where(RefreshLog.analysis_run_id == run.id))
    if log is None:
        return
    log.status = "completed" if run.status in {"completed", "completed_with_warnings"} else "failed"
    log.completed_at = utcnow_naive()
    if log.status == "completed":
        master = db.get(MasterDataSource, log.master_source_id)
        if master:
            master.last_success_analysis_run_id = run.id
            master.updated_at = utcnow_naive()
    db.commit()


def _module_name(batch: Batch) -> str:
    return batch.original_name


def activate_batch(db: Session, batch: Batch, created_by: str) -> DataModule:
    master = ensure_master(db, created_by=created_by)
    if batch.replaced_from_batch_id:
        old = db.get(Batch, batch.replaced_from_batch_id)
        if old is None or not old.data_module_id:
            raise ValueError("被替换的模块版本不存在")
        module = db.get(DataModule, old.data_module_id)
        if module is None:
            raise ValueError("数据模块不存在")
        max_revision = (
            db.scalar(
                select(func.max(Batch.revision)).where(
                    Batch.data_module_id == module.id, Batch.id != batch.id
                )
            )
            or 0
        )
        batch.data_module_id = module.id
        batch.revision = max_revision + 1
        batch.is_active = True
        old.is_active = False
        old.superseded_at = utcnow_naive()
        old.replaced_by_batch_id = batch.id
    else:
        module = DataModule(
            master_source_id=master.id,
            name=_module_name(batch),
            active_batch_id=batch.id,
            created_by=created_by,
        )
        db.add(module)
        db.flush()
        batch.data_module_id = module.id
        batch.revision = 1
        batch.is_active = True
    module.active_batch_id = batch.id
    module.updated_at = utcnow_naive()
    db.flush()
    enforce_module_retention(db, module.id)
    return module


def enforce_module_retention(db: Session, module_id: str) -> None:
    versions = list(
        db.scalars(
            select(Batch).where(Batch.data_module_id == module_id).order_by(Batch.created_at.desc())
        )
    )
    for old in versions[2:]:
        if old.file_deleted:
            continue
        for value in (old.stored_path, old.parquet_path):
            if value:
                path = Path(value)
                if path.exists():
                    path.unlink()
        old.file_deleted = True


def module_previous_batch(db: Session, module: DataModule) -> Batch | None:
    active = db.get(Batch, module.active_batch_id) if module.active_batch_id else None
    if active is None:
        return None
    return db.scalar(
        select(Batch)
        .where(
            Batch.data_module_id == module.id,
            Batch.id != active.id,
            Batch.is_active.is_(False),
            Batch.file_deleted.is_(False),
            Batch.status == "ready",
        )
        .order_by(Batch.created_at.desc())
        .limit(1)
    )


def module_view(db: Session, module: DataModule) -> dict[str, Any]:
    active = db.get(Batch, module.active_batch_id) if module.active_batch_id else None
    previous = module_previous_batch(db, module)
    return {
        "id": module.id,
        "name": module.name,
        "active_batch_id": active.id if active else None,
        "active_filename": active.original_name if active else None,
        "active_revision": active.revision if active else 0,
        "row_count": active.row_count if active else 0,
        "event_count": active.event_count if active else 0,
        "status": active.status if active else "missing",
        "uploaded_at": active.created_at if active else module.created_at,
        "previous_batch_id": previous.id if previous else None,
        "previous_filename": previous.original_name if previous else None,
        "previous_revision": previous.revision if previous else None,
        "previous_available": bool(previous),
    }


def refresh_log_view(db: Session, log: RefreshLog) -> dict[str, Any]:
    module = db.get(DataModule, log.module_id) if log.module_id else None
    from_batch = db.get(Batch, log.from_batch_id) if log.from_batch_id else None
    to_batch = db.get(Batch, log.to_batch_id) if log.to_batch_id else None
    return {
        "id": log.id,
        "module_id": log.module_id,
        "module_name": module.name if module else None,
        "trigger": log.trigger,
        "status": log.status,
        "analysis_run_id": log.analysis_run_id,
        "from_filename": from_batch.original_name if from_batch else None,
        "to_filename": to_batch.original_name if to_batch else None,
        "detail": json.loads(log.detail_json or "{}"),
        "created_at": log.created_at,
        "completed_at": log.completed_at,
    }


def master_workbench(db: Session) -> dict[str, Any]:
    master = ensure_master(db)
    modules = list(
        db.scalars(
            select(DataModule)
            .where(DataModule.master_source_id == master.id)
            .order_by(DataModule.created_at.desc())
        )
    )
    current = (
        db.get(AnalysisRun, master.current_analysis_run_id)
        if master.current_analysis_run_id
        else None
    )
    success = (
        db.get(AnalysisRun, master.last_success_analysis_run_id)
        if master.last_success_analysis_run_id
        else None
    )
    active = active_batches(db)
    total_rows = sum(item.row_count for item in active)
    total_events = 0
    unmatched_count = 0
    if success and success.summary_json:
        summary = json.loads(success.summary_json)
        total_events = int(summary.get("meta", {}).get("event_count", 0))
        unmatched_count = int(summary.get("quality", {}).get("unknown_mapping_events", 0))
    else:
        total_events = sum(item.event_count for item in active)
    logs = list(
        db.scalars(
            select(RefreshLog)
            .where(RefreshLog.master_source_id == master.id)
            .order_by(RefreshLog.created_at.desc())
            .limit(100)
        )
    )
    return {
        "master_id": master.id,
        "name": master.name,
        "current_analysis_id": master.current_analysis_run_id,
        "last_success_analysis_id": master.last_success_analysis_run_id,
        "analysis_status": current.status if current else None,
        "stage": current.phase if current else "idle",
        "progress": current.progress if current else 0,
        "module_count": len([item for item in active]),
        "total_rows": total_rows,
        "total_events": total_events,
        "unmatched_count": unmatched_count,
        "modules": [module_view(db, item) for item in modules],
        "logs": [refresh_log_view(db, item) for item in logs],
        "error_message": current.error_message if current else None,
    }


def revert_module(
    db: Session,
    *,
    module_id: str,
    user: User,
) -> AnalysisRun:
    module = db.get(DataModule, module_id)
    if module is None:
        raise ValueError("数据模块不存在")
    previous = module_previous_batch(db, module)
    if previous is None:
        raise ValueError("没有可恢复的上一版本")
    current = db.get(Batch, module.active_batch_id) if module.active_batch_id else None
    if current:
        current.is_active = False
        current.superseded_at = utcnow_naive()
    previous.is_active = True
    previous.superseded_at = None
    module.active_batch_id = previous.id
    module.updated_at = utcnow_naive()
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="revert_data_module",
            entity_type="data_module",
            entity_id=module.id,
            detail_json=canonical_json(
                {"from_batch_id": current.id if current else None, "to_batch_id": previous.id}
            ),
        )
    )
    db.commit()
    return create_master_analysis(
        db,
        trigger="revert_file",
        requested_by=user.id,
        module_id=module.id,
        from_batch_id=current.id if current else None,
        to_batch_id=previous.id,
    )
