from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.services.jobs import process_once

SAMPLE = Path(os.environ.get("AIM_SAMPLE_XLSX", "/Users/quality/Downloads/AIM原始数据.xlsx"))


def drain_jobs() -> None:
    with SessionLocal() as db:
        while process_once(db):
            pass


@pytest.mark.skipif(not SAMPLE.exists(), reason="AIM sample workbook not available")
def test_upload_auto_analysis_mapping_and_rerun(admin_client):
    with SAMPLE.open("rb") as stream:
        response = admin_client.post(
            "/api/v1/batches",
            files={
                "file": (
                    SAMPLE.name,
                    stream,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert response.status_code == 202, response.text
    batch = response.json()
    assert batch["status"] == "uploaded"

    drain_jobs()
    batches = admin_client.get("/api/v1/batches").json()
    assert batches[0]["status"] == "ready"
    assert batches[0]["row_count"] == 182
    assert batches[0]["event_count"] == 91

    specs = admin_client.get("/api/v1/admin/specs").json()
    assert len(specs) == 2
    parsed_spec = next(item for item in specs if item["source_batch_id"] == batch["id"])
    assert parsed_spec["enabled_points_json"] == '["T1-T2","T1-T3","T1-T4","T1-T5"]'

    workbench = admin_client.get(f"/api/v1/batches/{batch['id']}/workbench").json()
    assert workbench["analysis_id"]
    assert workbench["analysis_status"] in {"completed", "completed_with_warnings"}

    summary = admin_client.get(f"/api/v1/analyses/{workbench['analysis_id']}/summary").json()
    assert summary["kpis"]["total_input"] == 90
    assert summary["kpis"]["final_ng_qty"] == 78
    assert {row["point"]: row["count"] for row in summary["pareto"]} == {
        "T1-T2": 26,
        "T1-T3": 46,
        "T1-T4": 64,
        "T1-T5": 67,
    }

    mapping = admin_client.post(
        "/api/v1/mappings/editor",
        json={
            "name": "样例 Slot1 映射",
            "batch_id": batch["id"],
            "rows": [
                {
                    "source": {
                        "site_name": "V7X_P_Delta_T",
                        "equipment_id": "L1_P_Delta_T_1@965N1",
                        "config": "V965N1",
                        "slot": "1",
                    },
                    "target": {"cell": "Cell-1", "tester": "T01", "qpl": "QPL1"},
                    "match_count": 15,
                    "status": "mapped",
                }
            ],
        },
    )
    assert mapping.status_code == 200, mapping.text
    mapping_id = mapping.json()["mapping_version_id"]
    editor = admin_client.get(
        f"/api/v1/mapping-editor?batch_id={batch['id']}&mapping_version_id={mapping_id}"
    ).json()
    assert sum(row["match_count"] for row in editor["unmapped"]) == 76

    rerun = admin_client.post(
        f"/api/v1/analyses/{workbench['analysis_id']}/rerun-with",
        json={"spec_version_id": parsed_spec["id"], "mapping_version_id": mapping_id},
    )
    assert rerun.status_code == 202, rerun.text
    drain_jobs()
    rerun_id = rerun.json()["id"]
    rerun_summary = admin_client.get(f"/api/v1/analyses/{rerun_id}/summary").json()
    assert rerun_summary["quality"]["unknown_mapping_events"] == 76
    assert rerun_summary["kpis"]["final_ng_qty"] == 78
