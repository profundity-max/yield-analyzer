from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.services.jobs import process_once

SAMPLE = Path(os.environ.get("AIM_SAMPLE_XLSX", "/Users/quality/Downloads/AIM原始数据.xlsx"))


@pytest.mark.skipif(not SAMPLE.exists(), reason="AIM sample workbook not available")
def test_upload_analysis_flow(admin_client):
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

    with SessionLocal() as db:
        assert process_once(db) is True

    batches = admin_client.get("/api/v1/batches").json()
    assert batches[0]["status"] == "ready"
    assert batches[0]["row_count"] == 182
    assert batches[0]["event_count"] == 91

    specs = admin_client.get("/api/v1/admin/specs").json()
    assert len(specs) == 1
    spec = specs[0]
    assert admin_client.post(f"/api/v1/admin/specs/{spec['id']}/confirm").status_code == 200

    mapping = admin_client.post(
        "/api/v1/admin/mappings",
        json={
            "name": "sample mapping",
            "rules": [
                {
                    "equipment_id": "L1_P_Delta_T_1@965N1",
                    "site_name": "V7X_P_Delta_T",
                    "config": "V965N1",
                    "slot": "1",
                    "cell": "Cell-1",
                    "tester": "T01",
                    "qpl": "QPL1",
                }
            ],
        },
    )
    assert mapping.status_code == 200, mapping.text

    response = admin_client.post(
        "/api/v1/analyses",
        json={
            "name": "正式分析",
            "batch_ids": [batch["id"]],
            "spec_version_id": spec["id"],
            "mapping_version_id": mapping.json()["id"],
        },
    )
    assert response.status_code == 202, response.text
    run = response.json()

    with SessionLocal() as db:
        assert process_once(db) is True

    status = admin_client.get(f"/api/v1/analyses/{run['id']}").json()
    assert status["status"] in {"completed", "completed_with_warnings"}
    summary = admin_client.get(f"/api/v1/analyses/{run['id']}/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["kpis"]["total_input"] == 90
    assert summary.json()["meta"]["event_count"] == 91
