from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.parser import DEFAULT_POINTS, parse_file, write_parquet

SAMPLE = Path(os.environ.get("AIM_SAMPLE_XLSX", "/Users/quality/Downloads/AIM原始数据.xlsx"))


@pytest.mark.skipif(not SAMPLE.exists(), reason="AIM sample workbook not available")
def test_aim_sample_parser_and_dedup(tmp_path):
    parsed = parse_file(SAMPLE, DEFAULT_POINTS)
    assert parsed.headers[:6] == ["序号", "产品SN", "最终结果", "站点名称", "设备编号", "config"]
    assert parsed.spec is not None
    assert parsed.spec.enabled_points == DEFAULT_POINTS
    assert parsed.spec.rules["default"]["T1-T2"] == {"lsl": 0.0, "usl": 2.0}

    parquet = tmp_path / "events.parquet"
    count, duplicates, errors = write_parquet(parsed.events, parquet)
    assert count == 91
    assert duplicates == 91
    assert errors == 0
