"""
DuckDB 连接管理模块

提供单例连接，所有模块通过此模块获取 DuckDB 连接。
"""

import duckdb
from pathlib import Path

from src.config import (
    DATA_DIR, DUCKDB_MEMORY_LIMIT, DUCKDB_THREADS, DUCKDB_TEMP_DIR,
)


# DuckDB 持久化文件路径
DB_PATH = str(DATA_DIR / "yield_analyzer.duckdb")

_connection = None


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
