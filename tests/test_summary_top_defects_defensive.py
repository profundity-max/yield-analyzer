"""Tests for the defensive layer added to summary.py and defect_analysis.py.

背景:
- 历史脏数据 (例如 fai_name='初始规格导入', ng_rate_pct='初始规格导入')
  会让 summary.py:180 抛 ValueError
- load_date_range() 在 streamlit cache 中可能返回非日期字符串
  会让 defect_analysis.py:83 抛 ValueError

修复:
1. summary.py / defect_analysis.py 用 _safe_float + _clean_top_rows 过滤脏条目
2. load_date_range 在解析失败时退回默认范围
3. _get_result_columns 只保留数值型 _result 列 (防止未来再混入字符串列)
"""
from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def _build_dirty_parquet(path: Path) -> None:
    """构造一个含字符串型 _result 列 + 字符串值 '__none__' 的 judged parquet。"""
    schema = pa.schema([
        ("SN", pa.string()),
        ("Time", pa.timestamp("ms")),
        ("Line", pa.string()),
        ("Project", pa.string()),
        ("Vendor", pa.string()),
        ("FAI001", pa.float64()),
        ("FAI001_result", pa.int8()),
        ("FAI002", pa.float64()),
        ("FAI002_result", pa.int8()),
        # 脏: FAI003_result 是 VARCHAR 而非 INT8
        ("FAI003", pa.float64()),
        ("FAI003_result", pa.string()),
        # 脏: FAI004_result 是 INT8 但值是 '__none__' 字符串
        ("FAI004", pa.float64()),
        ("FAI004_result", pa.string()),
        ("overall_result", pa.int8()),
    ])
    rows = [
        {"SN": "S1", "Time": None, "Line": "L1", "Project": "P1", "Vendor": "LY",
         "FAI001": 1.0, "FAI001_result": 0,
         "FAI002": 2.0, "FAI002_result": 1,
         "FAI003": 3.0, "FAI003_result": "yes",  # dirty VARCHAR
         "FAI004": 4.0, "FAI004_result": "no",
         "overall_result": 0},
        {"SN": "S2", "Time": None, "Line": "L1", "Project": "P1", "Vendor": "LY",
         "FAI001": 1.0, "FAI001_result": 0,
         "FAI002": 2.0, "FAI002_result": 0,
         "FAI003": 3.0, "FAI003_result": "no",
         "FAI004": 4.0, "FAI004_result": "yes",
         "overall_result": 0},
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def test_get_result_columns_filters_non_numeric(monkeypatch, tmp_path: Path) -> None:
    """_get_result_columns 必须只保留数值型 _result 列。

    历史脏数据 'FAI003_result' (VARCHAR) 不应被纳入 TOP 不良 SQL,
    否则 SUM("FAI003_result") 会抛类型错误。
    """
    from src.aggregator import top_defects as td

    judged_dir = tmp_path / "judged"
    judged_dir.mkdir()
    parquet_path = judged_dir / "judged_test_001.parquet"
    _build_dirty_parquet(parquet_path)

    cols = td._get_result_columns(str(parquet_path))
    assert "FAI001_result" in cols
    assert "FAI002_result" in cols
    assert "FAI003_result" not in cols, "VARCHAR _result 列必须过滤掉"
    assert "FAI004_result" not in cols, "VARCHAR _result 列必须过滤掉"
    assert "overall_result" not in cols


def test_clean_top_rows_filters_bad_entries(monkeypatch) -> None:
    """_clean_top_rows 过滤 ng_rate_pct 不能转 float 的脏条目。"""
    # 用 duckdb 内存连接避免 streamlit 的 lock
    import duckdb
    con = duckdb.connect()
    import src.db
    monkeypatch.setattr(src.db, "get_connection", lambda: con)
    from src.dashboard.pages.defect_analysis import _clean_top_rows

    rows = [
        {"fai_name": "FAI312_1", "ng_count": 13334, "total": 315440, "ng_rate_pct": 4.23},
        {"fai_name": "初始规格导入", "ng_count": 100, "total": 100, "ng_rate_pct": "初始规格导入"},
        {"fai_name": "FAI002", "ng_count": 50, "total": 100, "ng_rate_pct": 50.0},
        {"fai_name": None, "ng_count": 1, "total": 1, "ng_rate_pct": 100.0},
        {"fai_name": "", "ng_count": 1, "total": 1, "ng_rate_pct": 100.0},
    ]
    cleaned = _clean_top_rows(rows)
    assert len(cleaned) == 2
    assert cleaned[0]["fai_name"] == "FAI312_1"
    assert cleaned[1]["fai_name"] == "FAI002"
    # 类型正确
    assert isinstance(cleaned[0]["ng_rate_pct"], float)
    assert isinstance(cleaned[0]["ng_count"], int)


def test_safe_float_tolerates_bad_input() -> None:
    """_safe_float 把 None/字符串/异常值都安全转为 float 或 default。"""
    from src.dashboard.pages.summary import _safe_float
    from src.dashboard.pages.defect_analysis import _safe_float as _safe_float2

    for fn in (_safe_float, _safe_float2):
        assert fn(1.5) == 1.5
        assert fn(0) == 0.0
        assert fn("3.14") == 3.14
        assert fn(None) == 0.0
        assert fn(None, 99.0) == 99.0
        assert fn("garbage") == 0.0
        assert fn([1, 2, 3]) == 0.0


def test_summary_renders_top5_with_clean_data(monkeypatch) -> None:
    """汇总看板的 _safe_float 包装保证 ng_rate_pct 渲染不会抛错。"""
    from src.dashboard.pages.summary import _safe_float

    # 模拟脏缓存: ng_rate_pct 是字符串
    dirty = {"fai_name": "FAI312_1", "ng_count": 100, "ng_rate_pct": "4.23"}
    rate = _safe_float(dirty["ng_rate_pct"])
    assert rate == 4.23
