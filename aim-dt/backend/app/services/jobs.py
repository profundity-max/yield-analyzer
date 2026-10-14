from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AnalysisRun, Batch, MappingVersion, SpecVersion
from app.services.analytics import analyze_parquet
from app.services.batches import process_batch
from app.services.rules import load_json

settings = get_settings()


class JobCancelled(RuntimeError):
    pass


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def recover_stale_jobs(db: Session) -> None:
    cutoff = utcnow_naive() - timedelta(seconds=settings.worker_stale_seconds)
    for batch in db.scalars(select(Batch).where(Batch.status.in_(["validating", "importing"]))):
        if batch.ready_at is None:
            batch.status = "uploaded"
    for run in db.scalars(select(AnalysisRun).where(AnalysisRun.status == "running")):
        if run.heartbeat_at is None or run.heartbeat_at.replace(tzinfo=None) < cutoff:
            run.status = "queued"
            run.phase = "recovered"
            run.progress = 0.0
    db.commit()


def claim_batch(db: Session) -> Batch | None:
    batch = db.scalar(
        select(Batch).where(Batch.status == "uploaded").order_by(Batch.created_at).limit(1)
    )
    if batch is None:
        return None
    batch.status = "validating"
    db.commit()
    return batch


def claim_analysis(db: Session) -> AnalysisRun | None:
    run = db.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.status == "queued")
        .order_by(AnalysisRun.created_at)
        .limit(1)
    )
    if run is None:
        return None
    run.status = "running"
    run.phase = "preparing"
    run.started_at = utcnow_naive()
    run.heartbeat_at = utcnow_naive()
    db.commit()
    return run


def process_analysis(db: Session, run: AnalysisRun) -> dict:
    try:
        spec = db.get(SpecVersion, run.spec_version_id)
        if spec is None or spec.status == "retired":
            raise ValueError("规格版本不存在或已退役")
        filters = json.loads(run.filters_json)
        batch_ids = filters.get("batch_ids") or []
        batch_query = select(Batch).where(Batch.status == "ready")
        if batch_ids:
            batch_query = batch_query.where(Batch.id.in_(batch_ids))
        batches = list(db.scalars(batch_query))
        if not batches:
            raise ValueError("没有处于 ready 状态的数据批次")
        paths = [Path(item.parquet_path) for item in batches if item.parquet_path]
        if not paths:
            raise ValueError("批次缺少 Parquet 文件")
        mapping_rules: list[dict] = []
        if run.mapping_version_id:
            mapping = db.get(MappingVersion, run.mapping_version_id)
            if mapping is None or mapping.status == "retired":
                raise ValueError("Mapping 版本不存在或已退役")
            mapping_rules = load_json(mapping.rules_json, [])
        spec_rules = {
            "enabled_points": load_json(spec.enabled_points_json, []),
            "rules": load_json(spec.rules_json, {"default": {}, "by_config": {}}),
        }
        snapshot_dir = settings.storage_path / "snapshots" / run.id
        run.snapshot_dir = str(snapshot_dir)
        run.phase = "analysing"
        run.progress = 10.0
        run.data_watermark = ",".join(sorted(item.file_sha256 for item in batches))
        run.heartbeat_at = utcnow_naive()
        db.commit()

        def heartbeat(total_events: int) -> None:
            db.refresh(run)
            if run.cancel_requested:
                raise JobCancelled("分析已取消")
            run.progress = min(90.0, 10.0 + total_events / 100_000 * 5)
            run.phase = f"analysing:{total_events}"
            run.heartbeat_at = utcnow_naive()
            db.commit()

        summary = analyze_parquet(
            paths,
            spec=spec_rules,
            mapping=mapping_rules,
            filters=filters,
            snapshot_dir=snapshot_dir,
            heartbeat=heartbeat,
        )
        warnings = summary.get("meta", {}).get("warnings", [])
        run.summary_json = json.dumps(summary, ensure_ascii=False)
        run.warnings_json = json.dumps(warnings, ensure_ascii=False)
        run.progress = 100.0
        run.phase = "completed"
        run.status = (
            "completed_with_warnings" if warnings or spec.status != "active" else "completed"
        )
        run.completed_at = utcnow_naive()
        run.heartbeat_at = run.completed_at
        db.commit()
        return summary
    except JobCancelled:
        db.rollback()
        run.status = "cancelled"
        run.phase = "cancelled"
        run.completed_at = utcnow_naive()
        db.commit()
        raise
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.phase = "failed"
        run.error_message = str(exc)
        run.completed_at = utcnow_naive()
        db.commit()
        raise


def process_once(db: Session) -> bool:
    batch = claim_batch(db)
    if batch is not None:
        process_batch(db, batch)
        return True
    run = claim_analysis(db)
    if run is not None:
        process_analysis(db, run)
        return True
    return False
