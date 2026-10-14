from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisRun, Batch, MappingVersion, SpecVersion, User
from app.services.parser import DEFAULT_POINTS, parse_file, write_parquet
from app.services.rules import canonical_json, fingerprint


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def process_batch(db: Session, batch: Batch) -> None:
    batch.status = "validating"
    batch.error_message = None
    db.commit()
    try:
        parsed = parse_file(Path(batch.stored_path), DEFAULT_POINTS)
        parquet_path = Path(batch.parquet_path or "")
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        event_count, duplicate_count, error_count = write_parquet(parsed.events, parquet_path)
        batch.status = "importing"
        db.commit()

        if parsed.spec is not None:
            spec_payload = {
                "enabled_points": parsed.spec.enabled_points,
                "rules": parsed.spec.rules,
                "source_headers": parsed.spec.source_headers,
            }
            spec_hash = fingerprint(spec_payload)
            existing = db.scalar(select(SpecVersion).where(SpecVersion.fingerprint == spec_hash))
            if existing is None:
                creator = db.get(User, batch.created_by)
                spec = SpecVersion(
                    name=f"{Path(batch.original_name).stem} 自动解析规格",
                    fingerprint=spec_hash,
                    status="draft",
                    enabled_points_json=canonical_json(parsed.spec.enabled_points),
                    rules_json=canonical_json(parsed.spec.rules),
                    source_batch_id=batch.id,
                    created_by=creator.id if creator else batch.created_by,
                )
                db.add(spec)

        batch.row_count = event_count + duplicate_count
        batch.event_count = event_count
        batch.duplicate_count = duplicate_count
        batch.error_count = error_count
        batch.summary_json = canonical_json(
            {
                "headers": parsed.headers,
                "warnings": parsed.warnings,
                "spec_detected": parsed.spec is not None,
                "spec_points": parsed.spec.enabled_points if parsed.spec else [],
            }
        )
        batch.status = "ready"
        batch.ready_at = utcnow_naive()
        db.flush()
        if parsed.spec is not None:
            spec_for_run = db.scalar(
                select(SpecVersion).where(SpecVersion.fingerprint == spec_hash)
            )
            mapping_for_run = db.scalar(
                select(MappingVersion).where(MappingVersion.status == "active").limit(1)
            )
            if spec_for_run is not None and mapping_for_run is not None:
                db.add(
                    AnalysisRun(
                        name=f"{Path(batch.original_name).stem} 临时分析",
                        filters_json=canonical_json({"batch_ids": [batch.id]}),
                        spec_version_id=spec_for_run.id,
                        mapping_version_id=mapping_for_run.id,
                        requested_by=batch.created_by,
                    )
                )
        db.commit()
    except Exception as exc:
        db.rollback()
        batch.status = "failed"
        batch.error_message = str(exc)
        db.commit()
        raise
