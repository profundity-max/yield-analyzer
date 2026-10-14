from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.services.analytics import analyze_parquet
from app.services.parser import PARQUET_SCHEMA, event_hash, event_id_from_hash


def make_event(sn: str, when: datetime, t1: float, t2: float) -> dict:
    measurements = {"T1-T2": t1, "T1-T3": t2, "T1-T4": 0.5, "T1-T5": 0.5, "T1-T6": 0.5}
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


def test_first_pass_and_retest_rules(tmp_path: Path):
    events = [
        make_event("SN-PASS", datetime(2026, 9, 26, 9), 1.0, 1.0),
        make_event("SN-RETEST", datetime(2026, 9, 26, 10), 3.0, 1.0),
        make_event("SN-RETEST", datetime(2026, 9, 26, 11), 1.0, 1.0),
        make_event("SN-NG", datetime(2026, 9, 26, 12), 1.0, 3.0),
    ]
    path = tmp_path / "events.parquet"
    pq.write_table(pa.Table.from_pylist(events, schema=PARQUET_SCHEMA), path)
    spec = {
        "enabled_points": ["T1-T2", "T1-T3", "T1-T4", "T1-T5", "T1-T6"],
        "rules": {
            "default": {
                point: {"lsl": 0, "usl": 2}
                for point in ["T1-T2", "T1-T3", "T1-T4", "T1-T5", "T1-T6"]
            },
            "by_config": {},
        },
    }
    summary = analyze_parquet(
        [path],
        spec=spec,
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
    assert summary["kpis"]["total_input"] == 3
    assert summary["kpis"]["first_pass_qty"] == 1
    assert summary["kpis"]["retest_pass_qty"] == 1
    assert summary["kpis"]["final_pass_qty"] == 2
    assert summary["kpis"]["final_ng_qty"] == 1
    assert summary["kpis"]["avg_processing_ms"] == 10.0
