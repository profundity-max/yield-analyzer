from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.services.analytics import analyze_parquet
from app.services.parser import PARQUET_SCHEMA, event_hash, event_id_from_hash


def event(sn: str, value: float | None) -> dict:
    measurements = {"T1-T2": value, "T1-T3": 1.0, "T1-T4": 1.0, "T1-T5": 1.0, "T1-T6": 1.0}
    when = datetime(2026, 9, 26, 9)
    digest = event_hash(sn, when, measurements)
    return {
        "event_id": event_id_from_hash(digest),
        "event_hash": digest,
        "sn": sn,
        "detected_at": when,
        "production_day": when.date(),
        "config": "V965N1",
        "site_name": "SITE",
        "equipment_id": "EQ1",
        "slot": "1",
        "processing_ms": 10.0,
        "original_final_result": "Fail",
        "measurement_json": __import__("json").dumps(measurements),
        "source_sequence": 1,
    }


def test_missing_and_sentinel_are_error_ng(tmp_path: Path):
    rows = [event("SN-MISSING", None), event("SN-SENTINEL", 9999.0)]
    path = tmp_path / "events.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=PARQUET_SCHEMA), path)
    points = ["T1-T2", "T1-T3", "T1-T4", "T1-T5", "T1-T6"]
    summary = analyze_parquet(
        [path],
        spec={
            "enabled_points": points,
            "rules": {"default": {p: {"lsl": 0, "usl": 2} for p in points}, "by_config": {}},
        },
        mapping=[
            {
                "equipment_id": "EQ1",
                "site_name": "SITE",
                "config": "V965N1",
                "slot": "1",
                "cell": "Cell-1",
                "tester": "T01",
                "qpl": "QPL1",
            }
        ],
        filters={},
        snapshot_dir=tmp_path / "snapshot",
    )
    assert summary["kpis"]["error_event_qty"] == 2
    assert summary["kpis"]["final_ng_qty"] == 2
