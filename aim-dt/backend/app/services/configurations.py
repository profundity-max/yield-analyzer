from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisBatch,
    AnalysisRun,
    AuditLog,
    Batch,
    Category,
    MappingVersion,
    SpecVersion,
    User,
)
from app.services.rules import canonical_json, fingerprint

DEFAULT_POINTS = ["T1-T2", "T1-T3", "T1-T4", "T1-T5"]
DEFAULT_LIMITS = {"lsl": 0.0, "usl": 2.0}
DEFAULT_CATEGORIES = {
    "cell": [f"Cell-{index}" for index in range(1, 7)],
    "tester": [f"T{index:02d}" for index in range(1, 11)],
    "qpl": [f"QPL{index}" for index in range(1, 4)],
}


def point_code_from_column(column: str) -> str | None:
    match = re.fullmatch(r"Temp_T(\d+)_T(\d+)", column or "", flags=re.IGNORECASE)
    if not match:
        return None
    return f"T{match.group(1)}-T{match.group(2)}"


def column_from_point(point: str) -> str:
    return "Temp_" + point.replace("-", "_")


def seed_categories(db: Session) -> None:
    for kind, codes in DEFAULT_CATEGORIES.items():
        for index, code in enumerate(codes, start=1):
            existing = db.scalar(
                select(Category).where(Category.kind == kind, Category.code == code)
            )
            if existing is None:
                db.add(Category(kind=kind, code=code, label=code, sort_order=index * 10))
    db.commit()


def ensure_default_spec(db: Session, created_by: str | None = None) -> SpecVersion:
    active = db.scalar(select(SpecVersion).where(SpecVersion.status == "active").limit(1))
    if active is not None:
        return active
    rules = {"default": {point: dict(DEFAULT_LIMITS) for point in DEFAULT_POINTS}, "by_config": {}}
    payload = {"name": "D-T 标准规格", "enabled_points": DEFAULT_POINTS, "rules": rules}
    digest = fingerprint(payload)
    spec = db.scalar(select(SpecVersion).where(SpecVersion.fingerprint == digest))
    if spec is None:
        spec = SpecVersion(
            name="D-T 标准规格",
            fingerprint=digest,
            status="active",
            enabled_points_json=canonical_json(DEFAULT_POINTS),
            rules_json=canonical_json(rules),
            created_by=created_by,
            confirmed_by=created_by,
        )
        db.add(spec)
    else:
        spec.status = "active"
    db.commit()
    db.refresh(spec)
    return spec


def detected_points(batch: Batch | None, rules: dict[str, Any] | None = None) -> dict[str, str]:
    found: dict[str, str] = {point: column_from_point(point) for point in DEFAULT_POINTS}
    if batch and batch.summary_json:
        try:
            summary = json.loads(batch.summary_json)
            for column in summary.get("headers") or []:
                point = point_code_from_column(str(column))
                if point:
                    found[point] = str(column)
        except json.JSONDecodeError:
            pass
    for point in (rules or {}).get("default", {}):
        found.setdefault(point, column_from_point(point))
    return dict(sorted(found.items(), key=lambda item: point_sort_key(item[0])))


def point_sort_key(point: str) -> tuple[int, int]:
    match = re.fullmatch(r"T(\d+)-T(\d+)", point)
    return (int(match.group(1)), int(match.group(2))) if match else (999, 999)


def spec_to_editor(spec: SpecVersion, batch: Batch | None = None) -> dict[str, Any]:
    enabled = set(json.loads(spec.enabled_points_json or "[]"))
    rules = json.loads(spec.rules_json or '{"default":{},"by_config":{}}')
    detected = detected_points(batch, rules)
    points = []
    for code, source_column in detected.items():
        limit = rules.get("default", {}).get(code, {})
        points.append(
            {
                "code": code,
                "source_column": source_column,
                "enabled": code in enabled,
                "lsl": limit.get("lsl", 0 if code in DEFAULT_POINTS else None),
                "usl": limit.get("usl", 2 if code in DEFAULT_POINTS else None),
                "detected": True,
            }
        )
    return {
        "id": spec.id,
        "name": spec.name,
        "status": spec.status,
        "points": points,
        "created_at": spec.created_at,
        "confirmed_at": spec.confirmed_at,
    }


def create_active_spec(
    db: Session,
    *,
    name: str,
    points: list[dict[str, Any]],
    user: User,
    source_batch_id: str | None,
) -> SpecVersion:
    enabled = [item["code"] for item in points if item.get("enabled")]
    rules = {
        "default": {
            item["code"]: {"lsl": item.get("lsl"), "usl": item.get("usl")} for item in points
        },
        "by_config": {},
    }
    payload = {
        "name": name,
        "enabled_points": enabled,
        "rules": rules,
        "source_batch_id": source_batch_id,
    }
    digest = fingerprint(payload)
    existing = db.scalar(select(SpecVersion).where(SpecVersion.fingerprint == digest))
    if existing is not None:
        existing.status = "active"
        existing.name = name
        spec = existing
    else:
        spec = SpecVersion(
            name=name,
            fingerprint=digest,
            status="active",
            enabled_points_json=canonical_json(enabled),
            rules_json=canonical_json(rules),
            source_batch_id=source_batch_id,
            created_by=user.id,
            confirmed_by=user.id,
        )
        db.add(spec)
        db.flush()
    for other in db.scalars(
        select(SpecVersion).where(SpecVersion.id != spec.id, SpecVersion.status == "active")
    ):
        other.status = "retired"
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="save_spec_editor",
            entity_type="spec",
            entity_id=spec.id,
            detail_json=canonical_json(payload),
        )
    )
    db.commit()
    db.refresh(spec)
    return spec


def categories_by_kind(db: Session, include_inactive: bool = False) -> dict[str, list[Category]]:
    query = select(Category).order_by(Category.kind, Category.sort_order, Category.code)
    if not include_inactive:
        query = query.where(Category.active.is_(True))
    result: dict[str, list[Category]] = {"cell": [], "tester": [], "qpl": []}
    for row in db.scalars(query):
        result.setdefault(row.kind, []).append(row)
    return result


def _dedup_path(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return str(path).replace("'", "''"), []


def distinct_source_combinations(batch: Batch) -> list[dict[str, Any]]:
    if not batch.parquet_path:
        return []
    path_literal, _ = _dedup_path(Path(batch.parquet_path))
    con = duckdb.connect(":memory:")
    try:
        rows = con.execute(
            f"""
            WITH combined AS (
                SELECT * FROM read_parquet('{path_literal}')
            ), dedup AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY event_hash ORDER BY detected_at, source_sequence
                ) AS rn
                FROM combined
            )
            SELECT COALESCE(site_name, '') AS site_name,
                   COALESCE(equipment_id, '') AS equipment_id,
                   COALESCE(config, '') AS config,
                   CAST(COALESCE(slot, '') AS VARCHAR) AS slot,
                   count(*) AS match_count
            FROM dedup
            WHERE rn = 1
            GROUP BY ALL
            ORDER BY match_count DESC, site_name, equipment_id, config, slot
            """
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "source": {
                "site_name": row[0] or None,
                "equipment_id": row[1] or None,
                "config": row[2] or None,
                "slot": row[3] or None,
            },
            "match_count": int(row[4]),
        }
        for row in rows
    ]


def _best_rule(source: dict[str, Any], rules: list[dict[str, Any]]) -> int | None:
    matched: list[tuple[int, int]] = []
    keys = ("site_name", "equipment_id", "config", "slot")
    for index, rule in enumerate(rules):
        score = 0
        valid = True
        for key in keys:
            expected = rule.get(key)
            actual = source.get(key)
            if expected not in (None, ""):
                if str(expected) != str(actual):
                    valid = False
                    break
                score += 1
        if valid:
            matched.append((score, index))
    return max(matched)[1] if matched else None


def mapping_editor_view(
    db: Session,
    *,
    batch: Batch,
    mapping: MappingVersion | None,
) -> dict[str, Any]:
    rules = json.loads(mapping.rules_json) if mapping and mapping.rules_json else []
    rows: list[dict[str, Any]] = []
    match_counts = [0] * len(rules)
    unmapped: list[dict[str, Any]] = []
    for combination in distinct_source_combinations(batch):
        source = combination["source"]
        index = _best_rule(source, rules)
        if index is None:
            unmapped.append(
                {
                    "source": source,
                    "target": {"cell": "Unassigned", "tester": "Unassigned", "qpl": "Unassigned"},
                    "match_count": combination["match_count"],
                    "status": "unmapped",
                }
            )
        else:
            match_counts[index] += combination["match_count"]
    for index, rule in enumerate(rules):
        rows.append(
            {
                "source": {
                    "site_name": rule.get("site_name"),
                    "equipment_id": rule.get("equipment_id"),
                    "config": rule.get("config"),
                    "slot": str(rule["slot"]) if rule.get("slot") is not None else None,
                },
                "target": {
                    "cell": rule.get("cell") or "Unassigned",
                    "tester": rule.get("tester") or "Unassigned",
                    "qpl": rule.get("qpl") or "Unassigned",
                },
                "match_count": match_counts[index],
                "status": "mapped",
            }
        )
    categories = categories_by_kind(db)
    return {
        "mapping_version_id": mapping.id if mapping else None,
        "mapping_name": mapping.name if mapping else None,
        "rules": rows,
        "unmapped": unmapped,
        "categories": {
            kind: [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "code": item.code,
                    "label": item.label,
                    "active": item.active,
                    "sort_order": item.sort_order,
                }
                for item in values
            ]
            for kind, values in categories.items()
        },
    }


def create_active_mapping(
    db: Session,
    *,
    name: str,
    rows: list[dict[str, Any]],
    user: User,
) -> MappingVersion:
    rules = [
        {
            "site_name": row["source"].get("site_name") or None,
            "equipment_id": row["source"].get("equipment_id") or None,
            "config": row["source"].get("config") or None,
            "slot": row["source"].get("slot") or None,
            "cell": row["target"].get("cell") or "Unassigned",
            "tester": row["target"].get("tester") or "Unassigned",
            "qpl": row["target"].get("qpl") or "Unassigned",
        }
        for row in rows
        if row.get("status") != "disabled"
    ]
    digest = fingerprint(rules)
    existing = db.scalar(select(MappingVersion).where(MappingVersion.fingerprint == digest))
    if existing is not None:
        existing.status = "active"
        existing.name = name
        mapping = existing
    else:
        mapping = MappingVersion(
            name=name,
            fingerprint=digest,
            status="active",
            rules_json=canonical_json(rules),
            created_by=user.id,
            confirmed_by=user.id,
        )
        db.add(mapping)
        db.flush()
    for other in db.scalars(
        select(MappingVersion).where(
            MappingVersion.id != mapping.id, MappingVersion.status == "active"
        )
    ):
        other.status = "retired"
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="save_mapping_editor",
            entity_type="mapping",
            entity_id=mapping.id,
            detail_json=canonical_json({"name": name, "rows": rows}),
        )
    )
    db.commit()
    db.refresh(mapping)
    return mapping


def link_analysis_batches(db: Session, run: AnalysisRun, batch_ids: list[str]) -> None:
    for batch_id in batch_ids:
        exists = db.scalar(
            select(AnalysisBatch).where(
                AnalysisBatch.analysis_run_id == run.id, AnalysisBatch.batch_id == batch_id
            )
        )
        if exists is None:
            db.add(AnalysisBatch(analysis_run_id=run.id, batch_id=batch_id))
    db.flush()


def latest_analysis_for_batch(db: Session, batch_id: str) -> AnalysisRun | None:
    return db.scalar(
        select(AnalysisRun)
        .join(AnalysisBatch, AnalysisBatch.analysis_run_id == AnalysisRun.id)
        .where(AnalysisBatch.batch_id == batch_id)
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )


def unmapped_count(db: Session, batch: Batch, mapping: MappingVersion | None) -> int:
    view = mapping_editor_view(db, batch=batch, mapping=mapping)
    return sum(row["match_count"] for row in view["unmapped"])
