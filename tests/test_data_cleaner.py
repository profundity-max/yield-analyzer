"""Tests for data_cleaner: vendor/project/line 必须存在, 否则整行剔除。"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.importer.data_cleaner import (
    REQUIRED_METADATA,
    aggregate,
    clean_file,
    clean_glob,
    inspect_file,
)


def _write_parquet(path: Path, rows: list[dict]) -> None:
    """把 dict 列表写成 parquet, 字段名与生产数据一致 (字符串 / 双精度)。"""
    if not rows:
        # 写一个空 parquet, schema 显式给出
        schema = pa.schema([(c, pa.string() if c != "Time" else pa.timestamp("ms")) for c in ("SN", "Time", "Vendor", "Project", "Line")])
        pq.write_table(pa.Table.from_pylist([], schema=schema), path)
        return
    schema = pa.schema([
        ("SN", pa.string()),
        ("Time", pa.timestamp("ms")),
        ("Vendor", pa.string()),
        ("Project", pa.string()),
        ("Line", pa.string()),
        ("FAI1", pa.float64()),
    ])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def _count(path: Path, where: str = "1=1") -> int:
    con = duckdb.connect()
    return con.execute(f'SELECT COUNT(*) FROM read_parquet("{path}") WHERE {where}').fetchone()[0]


def test_inspect_file_counts_each_missing_column(tmp_path: Path) -> None:
    f = tmp_path / "raw.parquet"
    _write_parquet(f, [
        {"SN": "S1", "Time": None, "Vendor": "LY", "Project": "P1", "Line": "L1", "FAI1": 1.0},
        {"SN": "S2", "Time": None, "Vendor": None, "Project": "P1", "Line": "L1", "FAI1": 2.0},
        {"SN": "S3", "Time": None, "Vendor": "LY", "Project": None, "Line": "L1", "FAI1": 3.0},
        {"SN": "S4", "Time": None, "Vendor": "LY", "Project": "P1", "Line": None, "FAI1": 4.0},
        {"SN": "S5", "Time": None, "Vendor": "LY", "Project": "P1", "Line": "", "FAI1": 5.0},  # empty str
        {"SN": "S6", "Time": None, "Vendor": "LY", "Project": "P1", "Line": "None", "FAI1": 6.0},  # literal "None"
    ])
    info = inspect_file(f)
    assert info["total_rows"] == 6
    assert info["invalid_total"] == 5  # S2 Vendor, S3 Project, S4 None Line, S5 "" Line, S6 "None" Line
    assert info["per_column"]["Vendor"] == 1
    assert info["per_column"]["Project"] == 1
    assert info["per_column"]["Line"] == 3  # None + "" + "None"


def test_clean_file_removes_invalid_and_is_atomic(tmp_path: Path) -> None:
    f = tmp_path / "raw.parquet"
    _write_parquet(f, [
        {"SN": "S1", "Time": None, "Vendor": "LY", "Project": "P1", "Line": "L1", "FAI1": 1.0},
        {"SN": "S2", "Time": None, "Vendor": None, "Project": "P1", "Line": "L1", "FAI1": 2.0},
        {"SN": "S3", "Time": None, "Vendor": "LY", "Project": None, "Line": "L1", "FAI1": 3.0},
    ])
    result = clean_file(f)
    assert result["removed"] == 2
    assert result["remaining"] == 1
    assert _count(f) == 1
    assert _count(f, '"SN" = \'S1\'') == 1


def test_clean_file_dry_run_does_not_modify(tmp_path: Path) -> None:
    f = tmp_path / "raw.parquet"
    _write_parquet(f, [
        {"SN": "S1", "Time": None, "Vendor": "LY", "Project": "P1", "Line": "L1", "FAI1": 1.0},
        {"SN": "S2", "Time": None, "Vendor": None, "Project": None, "Line": None, "FAI1": 2.0},
    ])
    result = clean_file(f, dry_run=True)
    assert result["removed"] == 1
    assert result["dry_run"] is True
    assert _count(f) == 2  # 文件未改


def test_clean_file_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        clean_file(tmp_path / "nope.parquet")


def test_clean_glob_returns_one_result_per_file(tmp_path: Path) -> None:
    for n, suffix in [("a", 0), ("b", 1), ("c", 2)]:
        rows = [
            {"SN": f"S-{n}-{i}", "Time": None, "Vendor": None if i == 0 else "LY",
             "Project": "P1", "Line": "L1", "FAI1": float(i)}
            for i in range(2)
        ]
        _write_parquet(tmp_path / f"raw_{n}.parquet", rows)
    results = clean_glob(tmp_path / "raw_*.parquet")
    assert len(results) == 3
    assert sum(r["removed"] for r in results) == 3
    agg = aggregate(results)
    assert agg["file_count"] == 3
    assert agg["total_rows"] == 6
    assert agg["removed"] == 3
    assert agg["remaining"] == 3
    assert agg["per_column"]["Vendor"] == 3


def test_required_metadata_includes_vendor_project_line() -> None:
    assert REQUIRED_METADATA == ("Vendor", "Project", "Line")


def test_clean_file_preserves_other_columns(tmp_path: Path) -> None:
    """确认清洗后其他 FAI 列仍完整保留。"""
    f = tmp_path / "raw.parquet"
    _write_parquet(f, [
        {"SN": "S1", "Time": None, "Vendor": "LY", "Project": "P1", "Line": "L1", "FAI1": 11.0},
        {"SN": "S2", "Time": None, "Vendor": None, "Project": "P1", "Line": "L1", "FAI1": 22.0},
    ])
    clean_file(f)
    rows = duckdb.connect().execute(
        f'SELECT "SN", "FAI1" FROM read_parquet("{f}") ORDER BY "SN"'
    ).fetchall()
    assert rows == [("S1", 11.0)]
