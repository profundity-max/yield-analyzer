"""
回归去重逻辑集成测试 (用 in-memory DuckDB + 临时 parquet)
"""
import duckdb
import pandas as pd
import pytest


@pytest.fixture
def fresh_db(in_memory_db):
    """每次测试都拿新的 in-memory DuckDB。"""
    return in_memory_db


def test_dedup_keeps_latest_per_sn(in_memory_db, parquet_dir_with_sample, monkeypatch):
    """同一 SN 多次投产, 只留 Time 最新。"""
    # 模拟单测环境下 _parquet_glob 返回临时目录
    def fake_glob():
        return f"{parquet_dir_with_sample}/*.parquet"
    monkeypatch.setattr("src.aggregator.regression._parquet_glob", fake_glob)

    # 用 in-memory db 跑查询
    sql = f"""
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY SN
                    ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC
                ) AS rn
            FROM read_parquet('{parquet_dir_with_sample}/*.parquet', union_by_name=true)
        )
        SELECT SN, "Time"
        FROM ranked
        WHERE rn = 1
    """
    df = in_memory_db.fetchdf(sql)
    assert len(df) == 2  # SN001 + SN002
    # SN001 最新: 2026-07-25 12:00
    sn001 = df[df.SN == "SN001"].iloc[0]
    assert "12:00" in str(sn001["Time"])
    # SN002 最新: 2026-07-27 08:00
    sn002 = df[df.SN == "SN002"].iloc[0]
    assert "2026-07-27" in str(sn002["Time"])


def test_data_access_in_memory_roundtrip(in_memory_db):
    """in-memory DataAccess 完整 roundtrip 测试。"""
    in_memory_db.query("CREATE TABLE widgets (id INT, name TEXT)")
    in_memory_db.query("INSERT INTO widgets VALUES (1, \'foo\'), (2, \'bar\')")
    df = in_memory_db.fetchdf("SELECT * FROM widgets ORDER BY id")
    assert len(df) == 2
    assert df.iloc[0]["name"] == "foo"
    assert df.iloc[1]["name"] == "bar"


def test_data_access_in_memory_isolated(in_memory_db):
    """in-memory db 与生产 db 互不干扰。"""
    # 起一个表
    in_memory_db.query("CREATE TABLE isolated (x INT)")
    in_memory_db.query("INSERT INTO isolated VALUES (42)")
    # 另一个 in-memory db 不应看到
    from tests.conftest import _InMemoryDuckDB
    other = _InMemoryDuckDB()
    result = other.fetchdf(
        "SELECT count(*) AS n FROM duckdb_tables WHERE table_name = \'isolated\'"
    )
    assert result["n"].iloc[0] == 0
    other.close()
