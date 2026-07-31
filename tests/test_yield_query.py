"""
YieldQuery deep module 单元测试
"""
import duckdb
import pytest
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

from src.aggregator.yield_query import (
    YieldQuery, QuerySpec, get_default_query, set_default_query,
)
from src.aggregator.data_source import ParquetSource


@pytest.fixture
def sample_parquet_dir(tmp_path):
    """创建带样本数据的临时目录"""
    table = pa.table({
        "SN": ["SN001", "SN001", "SN002", "SN003"],
        "Project": ["967E1", "967E1", "967E1", "967E2"],
        "Vendor": ["LY", "LY", "LK", "LY"],
        "Line": ["L1", "L1", "L1", "L2"],
        "Time": ["2026-07-25 10:00", "2026-07-25 12:00",
                 "2026-07-26 09:00", "2026-07-27 08:00"],
        "FAI001": [10.0, 10.5, 9.8, 10.2],
        "FAI001_result": [0, 0, 1, 0],
        "FAI002": [20.0, 20.1, 19.9, 20.0],
        "FAI002_result": [0, 0, 0, 0],
        "overall_result": [0, 0, 1, 0],
    })
    pq_dir = tmp_path / "judged"
    pq_dir.mkdir()
    pq.write_table(table, str(pq_dir / "judged_test.parquet"))
    return str(pq_dir)


@pytest.fixture
def in_mem_conn():
    """in-memory DuckDB"""
    return duckdb.connect(":memory:")


class TestQuerySpec:
    def test_basic(self):
        spec = QuerySpec("FOO", lambda r: {"x": r[0]})
        assert spec.template_name == "FOO"
        assert spec.row_mapper is not None
        assert spec.extra_context == {}

    def test_with_extra(self):
        spec = QuerySpec("X", lambda r: {}, extra_context={"top_n": 10})
        assert spec.extra_context == {"top_n": 10}

    def test_frozen(self):
        spec = QuerySpec("X", lambda r: {})
        with pytest.raises((AttributeError, Exception)):
            spec.template_name = "Y"


class TestYieldQuery:
    def test_fetch_one(self, in_mem_conn):
        from src.aggregator import queries as q
        setattr(q, "T_TEMPLATE_1", "SELECT 42 as a, 'hi' as g")
        try:
            spec = QuerySpec("T_TEMPLATE_1", lambda r: {"a": r[0], "g": r[1]})
            qy = YieldQuery(conn_factory=lambda: in_mem_conn)
            assert qy.fetch_one(spec) == {"a": 42, "g": "hi"}
        finally:
            delattr(q, "T_TEMPLATE_1")

    def test_fetch_all(self, in_mem_conn):
        from src.aggregator import queries as q
        setattr(q, "T_TEMPLATE_2", "SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3")
        try:
            spec = QuerySpec("T_TEMPLATE_2", lambda r: {"x": r[0]})
            qy = YieldQuery(conn_factory=lambda: in_mem_conn)
            result = qy.fetch_all(spec)
            assert [r["x"] for r in result] == [1, 2, 3]
        finally:
            delattr(q, "T_TEMPLATE_2")

    def test_fetch_one_empty_returns_none(self, in_mem_conn):
        from src.aggregator import queries as q
        setattr(q, "T_TEMPLATE_3", "SELECT 1 WHERE FALSE")
        try:
            spec = QuerySpec("T_TEMPLATE_3", lambda r: {"x": r[0]})
            qy = YieldQuery(conn_factory=lambda: in_mem_conn)
            assert qy.fetch_one(spec) is None
        finally:
            delattr(q, "T_TEMPLATE_3")


class TestSingleton:
    def test_default_is_singleton(self):
        assert get_default_query() is get_default_query()

    def test_set_replaces(self):
        original = get_default_query()
        try:
            fake = YieldQuery(conn_factory=lambda: None)
            set_default_query(fake)
            assert get_default_query() is fake
        finally:
            set_default_query(original)


class TestIntegration:
    def test_with_real_parquet(self, sample_parquet_dir, in_mem_conn):
        """集成: 真实 Parquet + 自定义 source/conn"""
        from src.aggregator import queries as q
        # DAILY_YIELD_QUERY 需要 cutoff_hour 和 cfg_filter
        spec = QuerySpec(
            "DAILY_YIELD_QUERY",
            lambda r: {"day": str(r[0]), "total": r[1], "ok": r[2]},
            extra_context={"cutoff_hour": 7, "cfg_filter": None},
        )
        custom = YieldQuery(
            source=ParquetSource(Path(sample_parquet_dir)),
            conn_factory=lambda: in_mem_conn,
        )
        rows = custom.fetch_all(spec)
        total_rows = sum(r["total"] for r in rows)
        assert total_rows == 4  # 4 SN records
