"""Data cleaner — 去除缺失必填元数据 (Vendor/Project/Line) 的脏数据

设计:
- 必填元数据三件套: Vendor, Project, Line (缺一即视为脏)
- 空值判定: NULL, 空字符串, "None" 字面量
- 写入策略: 使用 DuckDB COPY 原子替换原 parquet 文件
- 统计: 总行数 / 各列脏行数 / 实际剔除行数 / 剩余行数

原则 (来自 codebase-design):
- Pure module + IO 分离: 这里只关心 parquet 清洗规则, 不 import dashboard
- 接口简单: clean_file(path) → dict; clean_glob(pattern) → list[dict]
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

import duckdb

logger = logging.getLogger(__name__)

# 必填元数据列 (任何一行缺这些都视为脏数据)
REQUIRED_METADATA = ("Vendor", "Project", "Line")


def _is_missing(value) -> bool:
    """判定单元格是否为「空」。

    视为空的:
    - None
    - 空字符串 / 仅空白 / 字符串 "None"
    """
    if value is None:
        return True
    s = str(value).strip()
    if not s or s.lower() == "none":
        return True
    return False


def _missing_columns_sql() -> str:
    """生成 SQL 片段: 行级脏判定 (任意必填列为空)。"""
    parts = [f'("{c}" IS NULL OR TRIM(CAST("{c}" AS VARCHAR)) IN (\'\', \'None\'))' for c in REQUIRED_METADATA]
    return " OR ".join(parts)


def inspect_file(parquet_path: str | Path) -> dict:
    """查看 parquet 文件中脏数据分布 (不修改文件)。

    Returns:
        dict {
            path: 文件路径,
            total_rows: 总行数,
            invalid_total: 至少一个必填列为空的行数,
            per_column: {col: 该列为空的行数},
        }
    """
    path = Path(parquet_path)
    con = duckdb.connect(":memory:")
    try:
        total = con.execute(f'SELECT COUNT(*) FROM read_parquet("{path}")').fetchone()[0]
        invalid_total = con.execute(
            f'SELECT COUNT(*) FROM read_parquet("{path}") WHERE {_missing_columns_sql()}'
        ).fetchone()[0]
        per_column = {}
        for col in REQUIRED_METADATA:
            per_column[col] = con.execute(
                f'SELECT COUNT(*) FROM read_parquet("{path}") '
                f'WHERE "{col}" IS NULL OR TRIM(CAST("{col}" AS VARCHAR)) IN (\'\', \'None\')'
            ).fetchone()[0]
        return {
            "path": str(path),
            "total_rows": total,
            "invalid_total": invalid_total,
            "per_column": per_column,
        }
    finally:
        con.close()


def clean_file(parquet_path: str | Path, *, dry_run: bool = False) -> dict:
    """清洗单个 parquet 文件: 删除缺失必填元数据的行, 原子替换原文件。

    Args:
        parquet_path: 待清洗的 parquet 文件路径
        dry_run: True 时只统计不写入

    Returns:
        dict {
            path, total_rows, removed, remaining,
            per_column: {col: 该列被剔除的行数 (缺失该列的行数)},
        }
    """
    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(f"parquet 文件不存在: {path}")

    before = inspect_file(path)
    removed = before["invalid_total"]

    if dry_run or removed == 0:
        logger.info(
            "[%s] %s: rows=%d invalid=%d (dry_run=%s)",
            "DRY" if dry_run else "OK", path.name, before["total_rows"], removed, dry_run,
        )
        return {
            "path": str(path),
            "total_rows": before["total_rows"],
            "removed": removed,
            "remaining": before["total_rows"] - removed,
            "per_column": before["per_column"],
            "dry_run": dry_run,
        }

    # 实际清洗: 写入临时文件, 再原子替换
    tmp_path = path.with_suffix(path.suffix + ".clean_tmp")
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            f"""
            COPY (
                SELECT * FROM read_parquet('{path}')
                WHERE NOT ({_missing_columns_sql()})
            ) TO '{tmp_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)
            """
        )
        os.replace(tmp_path, path)
    finally:
        con.close()

    after_total = before["total_rows"] - removed
    logger.info(
        "[CLEAN] %s: rows=%d → %d (removed %d)",
        path.name, before["total_rows"], after_total, removed,
    )
    return {
        "path": str(path),
        "total_rows": before["total_rows"],
        "removed": removed,
        "remaining": after_total,
        "per_column": before["per_column"],
        "dry_run": False,
    }


def clean_glob(pattern: str | Path, *, dry_run: bool = False) -> list[dict]:
    """按 glob 模式批量清洗 parquet。

    Args:
        pattern: glob 模式 (绝对路径)
        dry_run: True 时只统计

    Returns:
        每文件的清洗结果列表
    """
    pattern = str(pattern)
    paths = sorted(Path("/").glob(pattern.lstrip("/"))) if pattern.startswith("/") else sorted(Path(".").glob(pattern))
    if not paths:
        logger.warning("no parquet files match: %s", pattern)
        return []
    return [clean_file(p, dry_run=dry_run) for p in paths]


def aggregate(results: Iterable[dict]) -> dict:
    """汇总多文件清洗结果。"""
    rs = list(results)
    return {
        "file_count": len(rs),
        "total_rows": sum(r["total_rows"] for r in rs),
        "removed": sum(r["removed"] for r in rs),
        "remaining": sum(r["remaining"] for r in rs),
        "per_column": {
            col: sum(r["per_column"].get(col, 0) for r in rs)
            for col in REQUIRED_METADATA
        },
    }
