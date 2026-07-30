"""
DuckDB 连接管理模块

提供单例连接，所有模块通过此模块获取 DuckDB 连接。
"""

import duckdb
from pathlib import Path
from src.config import DUCKDB_MEMORY_LIMIT, DUCKDB_THREADS, DUCKDB_TEMP_DIR

from src.config import DATA_DIR

import contextlib
from typing import Iterator, Optional


class DataAccess:
    """
    DuckDB 数据访问 adapter（可注入）

    生产场景: DataAccess(path)  → 真实 duckdb 文件
    测试场景: DataAccess(":memory:")  → 内存库, 不锁文件

    关键设计:
      - 实例化时建立连接, dispose() 时关闭
      - 线程不安全 (DuckDB 连接不能跨线程), 但所有调用都在 Streamlit 单线程内
      - SQL 模板仍由各模块自管, 这里只负责"执行 + 返回"
    """

    def __init__(self, path: Optional[str] = None, read_only: bool = False):
        import duckdb as _duckdb
        if path is None:
            path = DB_PATH
        self._conn = _duckdb.connect(path, read_only=read_only) if path != ":memory:" else _duckdb.connect(path)
        if path != ":memory:":
            # 生产环境的性能配置
            self._conn.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
            self._conn.execute(f"SET threads={DUCKDB_THREADS}")
            self._conn.execute(f"SET temp_directory='{DUCKDB_TEMP_DIR}'")
            self._conn.execute("SET preserve_insertion_order=false")

    def query(self, sql: str, params: dict = None):
        """执行 SQL, 返回 DuckDB Relation。"""
        if params:
            return self._conn.execute(sql, params)
        return self._conn.execute(sql)

    def fetchdf(self, sql: str, params: dict = None):
        """执行 SQL, 直接返回 pandas DataFrame。"""
        if params:
            return self._conn.execute(sql, params).fetchdf()
        return self._conn.execute(sql).fetchdf()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()



_connection = None

# DuckDB 持久化文件路径
DB_PATH = str(DATA_DIR / "yield_analyzer.duckdb")


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    获取 DuckDB 连接（单例）

    首次调用时创建文件持久化连接并应用性能配置。
    后续调用返回同一连接，避免重复初始化开销。

    Args:
        read_only: 是否为只读模式（暂未实现，保留接口）
    """
    global _connection

    if _connection is None:
        _connection = duckdb.connect(DB_PATH)

        # 应用性能配置
        _connection.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        _connection.execute(f"SET threads={DUCKDB_THREADS}")
        _connection.execute(f"SET temp_directory='{DUCKDB_TEMP_DIR}'")
        _connection.execute("SET preserve_insertion_order=false")

    return _connection


def close_connection():
    """关闭 DuckDB 连接"""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def init_spec_tables():
    """
    初始化 Spec 相关的 DuckDB 持久化表

    这些表用于规格版本管理和配置存储。
    """
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS spec_versions (
            version_id    VARCHAR PRIMARY KEY,
            source_file   VARCHAR,
            imported_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active     BOOLEAN DEFAULT TRUE,
            description   VARCHAR
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS spec_limits (
            id            BIGINT PRIMARY KEY,
            version_id    VARCHAR,
            fai_name      VARCHAR NOT NULL,
            lower_limit   DOUBLE,
            upper_limit   DOUBLE,
            nominal       DOUBLE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key           VARCHAR PRIMARY KEY,
            value         VARCHAR,
            updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 确保有自增序列
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_spec_limits_id START 1
    """)


def query_parquet(sql: str, params: dict = None) -> duckdb.DuckDBPyRelation:
    """
    执行针对 Parquet 文件的 SQL 查询

    Args:
        sql: SQL 查询语句
        params: 可选的参数字典

    Returns:
        DuckDB 查询结果
    """
    conn = get_connection()
    if params:
        return conn.execute(sql, params)
    return conn.execute(sql)
