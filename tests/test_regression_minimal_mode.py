"""Tests for regression: minimal 列模式 — 排除 _result / overall_result。

背景:
- 旧版用 columns='all' 会 SELECT *, 再 client-side drop _result 列
  → DuckDB 仍要读取所有 _result 列, 浪费 IO 和内存
- 新版 columns='minimal' 用 DuckDB COLUMNS lambda 在 SQL 层做列剪枝
  → parquet 列读取减半, 网络序列化减半, pandas DataFrame 内存减半

约定:
- 'core'    = 7 个关键列 (含 overall_result, 不含 _result 列)
- 'minimal' = metadata + 全部测量列, 排除 _result 和 overall_result
- 'all'     = 全列 (向后兼容, 客户端 drop _result)
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.aggregator import data_source as ds


def _build_test_parquet(path: Path) -> None:
    """构造带 _result 列 + overall_result 的 judged parquet 测试数据。"""
    schema = pa.schema([
        ("SN", pa.string()),
        ("Time", pa.timestamp("ms")),
        ("Line", pa.string()),
        ("Project", pa.string()),
        ("Vendor", pa.string()),
        ("Yield3", pa.string()),
        ("FAI001", pa.float64()),
        ("FAI001_result", pa.int8()),
        ("FAI002", pa.float64()),
        ("FAI002_result", pa.int8()),
        ("overall_result", pa.int8()),
        ("judged_at", pa.timestamp("ms")),
        ("spec_version", pa.string()),
    ])
    rows = [
        {"SN": "S1", "Time": None, "Line": "L1", "Project": "P1", "Vendor": "LY", "Yield3": "Y3",
         "FAI001": 1.0, "FAI001_result": 0, "FAI002": 2.0, "FAI002_result": 0,
         "overall_result": 0, "judged_at": None, "spec_version": "v1"},
        {"SN": "S1", "Time": None, "Line": "L1", "Project": "P1", "Vendor": "LY", "Yield3": "Y3",
         "FAI001": 1.5, "FAI001_result": 1, "FAI002": 2.5, "FAI002_result": 1,
         "overall_result": 1, "judged_at": None, "spec_version": "v1"},
        {"SN": "S2", "Time": None, "Line": "L2", "Project": "P1", "Vendor": "LY", "Yield3": "Y3",
         "FAI001": 3.0, "FAI001_result": 0, "FAI002": 4.0, "FAI002_result": 0,
         "overall_result": 0, "judged_at": None, "spec_version": "v1"},
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


@pytest.fixture
def fake_source(monkeypatch, tmp_path: Path):
    """把 default_source 替换成 tmp_path/judged/judged_test_001.parquet。"""
    judged_dir = tmp_path / "judged"
    judged_dir.mkdir()
    parquet_path = judged_dir / "judged_test_001.parquet"
    _build_test_parquet(parquet_path)

    fake = ds.ParquetSource(judged_dir)

    from src.aggregator import regression as reg
    import src.db
    monkeypatch.setattr(ds, "_default_source", fake)
    monkeypatch.setattr(reg, "get_default_source", lambda: fake)
    # 每个测试用独立 DuckDB 连接, 避免全局 lock 冲突
    monkeypatch.setattr(src.db, "get_connection", lambda: duckdb.connect())
    monkeypatch.setattr(reg, "get_connection", lambda: duckdb.connect())
    return fake


def test_minimal_mode_excludes_result_columns(fake_source) -> None:
    from src.aggregator.regression import get_regression_unique_sn
    df = get_regression_unique_sn(columns="minimal")
    assert len(df) == 2  # S1 和 S2 各 1 行 (回归去重)
    assert not any(c.endswith("_result") for c in df.columns), \
        f"minimal 不应含 _result 列, 但有: {[c for c in df.columns if c.endswith('_result')]}"
    assert "overall_result" not in df.columns
    # 必须保留元数据 + 测量列
    assert "SN" in df.columns
    assert "Line" in df.columns
    assert "FAI001" in df.columns
    assert "FAI002" in df.columns


def test_core_mode_keeps_overall_result_but_no_per_fai_result(fake_source) -> None:
    """core 模式: 7 个关键列, 包含 overall_result 但不含 _result 列。"""
    from src.aggregator.regression import get_regression_unique_sn
    df = get_regression_unique_sn(columns="core")
    assert len(df) == 2
    assert "overall_result" in df.columns
    assert not any(c.endswith("_result") and c != "overall_result" for c in df.columns)


def test_all_mode_includes_everything(fake_source) -> None:
    """all 模式向后兼容, 客户端 drop _result 后等于 minimal。"""
    from src.aggregator.regression import get_regression_unique_sn
    df = get_regression_unique_sn(columns="all")
    assert len(df) == 2
    cols = set(df.columns)
    assert "FAI001" in cols
    assert "FAI002" in cols


def test_minimal_mode_generated_sql_uses_columns_lambda(fake_source) -> None:
    """验证 minimal 模式生成的 SQL 使用 DuckDB COLUMNS lambda 做列剪枝。"""
    from src.aggregator.regression import _build_unique_sn_query
    sql = _build_unique_sn_query(columns="minimal")
    assert "COLUMNS(c ->" in sql
    assert "_result" in sql
    assert "overall_result" in sql


def test_invalid_columns_value_falls_back_to_all(fake_source) -> None:
    """未知 columns 值回落到 SELECT * (向后兼容)。"""
    from src.aggregator.regression import _build_unique_sn_query
    sql = _build_unique_sn_query(columns="bogus")
    assert "SELECT *" in sql
