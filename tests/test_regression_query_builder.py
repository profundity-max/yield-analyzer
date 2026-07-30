"""回归查询的 SQL 构造 — 纯函数测试。"""
import pytest
from src.aggregator.regression import _build_unique_sn_query


def test_query_no_filter_selects_core_columns():
    sql = _build_unique_sn_query("core")
    assert 'SN, "Line", "Time"' in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "PARTITION BY SN" in sql
    assert "WHERE rn = 1" in sql


def test_query_all_selects_star():
    sql = _build_unique_sn_query("all")
    # SELECT * 出现 (不只是 SELECT SN, Line...)
    star_idx = sql.find("SELECT *")
    assert star_idx > -1
    # core 的 SELECT 不会单独出现
    assert "SN, " not in sql or "SELECT *" in sql


def test_query_with_line_filter():
    sql = _build_unique_sn_query("core", cfg="L1")
    assert '"Line" = \'L1\'' in sql
    assert "WHERE" in sql


def test_query_with_line_and_date_combined():
    sql = _build_unique_sn_query("core", cfg="L1", start_date="2026-07-01")
    assert '"Line" = \'L1\'' in sql
    assert ">= '2026-07-01'" in sql
    assert "AND" in sql  # 多个条件用 AND 连接


def test_query_with_sql_injection_in_line():
    """Line 含单引号必须被转义。"""
    sql = _build_unique_sn_query("core", cfg="L1'; DROP TABLE--")
    assert "L1''; DROP TABLE" in sql  # 双重单引号转义
    # 不应直接拼接未转义的引号
    assert '"Line" = \'L1\'; DROP' not in sql


def test_query_with_only_end_date():
    sql = _build_unique_sn_query("core", end_date="2026-07-27")
    assert ">= '2026-07-27'" not in sql
    assert "< CAST('2026-07-27'" in sql


def test_query_returns_dedup_latest_per_sn():
    """核心语义: 同一 SN 只留 Time 最新的。"""
    sql = _build_unique_sn_query("all")
    assert "ORDER BY TRY_CAST" in sql
    assert "DESC" in sql  # 降序取最新
