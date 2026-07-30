"""
SN 去重逻辑

对已判定的良率数据执行 SN（序列号）回归规则去重。

业务规则：
  - 同一 SN 可能出现多次（产线返修 / 复测）
  - 保留最新一条记录（按 time 字段降序）
  - 同时记录该 SN 的首次出现时间（first_time），用于回归分析

实现方式：DuckDB 窗口函数（ROW_NUMBER + MIN），高效处理大量数据。
"""

import logging
from typing import Optional

import duckdb

from src.config import JUDGED_DIR

logger = logging.getLogger(__name__)


def apply_regression_rules(
    conn: duckdb.DuckDBPyConnection,
    source_pattern: Optional[str] = None,
    view_name: str = "judged_dedup",
) -> duckdb.DuckDBPyRelation:
    """
    对已判定数据执行 SN 回归去重规则。

    使用 DuckDB 窗口函数：
    - ROW_NUMBER() OVER (PARTITION BY sn ORDER BY time DESC)
      为每个 SN 的记录按时间降序编号，rn=1 为最新记录
    - MIN(time) OVER (PARTITION BY sn)
      记录该 SN 最早出现时间，用于回归分析

    结果创建为一个 DuckDB VIEW，可直接查询或导出。

    Args:
        conn: DuckDB 连接
        source_pattern: judged parquet 文件的 glob 模式。
                        默认读取 data/judged/ 下所有 judged_*.parquet
        view_name: 创建的视图名称（默认 "judged_dedup"）

    Returns:
        DuckDBPyRelation: 去重后的数据查询结果

    Example:
        >>> conn = get_connection()
        >>> result = apply_regression_rules(conn)
        >>> # 查询去重后数据
        >>> df = conn.execute("SELECT * FROM judged_dedup").fetchdf()
        >>> # 统计回归情况
        >>> conn.execute('''
        ...     SELECT
        ...         COUNT(*) AS total_sn,
        ...         SUM(CASE WHEN time > first_time THEN 1 ELSE 0 END) AS regressed_sn
        ...     FROM judged_dedup
        ... ''').fetchone()
    """
    # ── 确定数据源 ───────────────────────────────────────────
    if source_pattern is None:
        source_pattern = str(JUDGED_DIR / "judged_*.parquet")

    # ── 列存在性检查 ─────────────────────────────────────────
    # 先探测有哪些列可用，兼容不同版本的 judged 数据
    sample_cols = _detect_columns(conn, source_pattern)
    has_overall = "overall_result" in sample_cols
    has_judged_at = "judged_at" in sample_cols

    # ── 构建查询 ─────────────────────────────────────────────
    # 根据实际列动态构建 SELECT 列表
    if has_overall and has_judged_at:
        sql = f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT * FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (PARTITION BY sn ORDER BY time DESC) AS rn,
                    MIN(time) OVER (PARTITION BY sn) AS first_time
                FROM read_parquet('{source_pattern}')
            ) sub
            WHERE rn = 1
        """
    else:
        # 兼容旧版 judged 数据（可能无 overall_result/judged_at 列）
        logger.warning("judged 数据缺少 overall_result 或 judged_at 列，使用兼容模式")
        sql = f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT * FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (PARTITION BY sn ORDER BY time DESC) AS rn,
                    MIN(time) OVER (PARTITION BY sn) AS first_time
                FROM read_parquet('{source_pattern}')
            ) sub
            WHERE rn = 1
        """

    conn.execute(sql)

    # ── 统计信息 ─────────────────────────────────────────────
    stats = conn.execute(f"""
        SELECT
            COUNT(*) AS unique_sn_count,
            SUM(CASE WHEN time > first_time THEN 1 ELSE 0 END) AS regressed_count,
            ROUND(
                SUM(CASE WHEN time > first_time THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2
            ) AS regression_rate_pct
        FROM {view_name}
    """).fetchone()

    logger.info(
        "SN 去重完成: %d 个唯一 SN, %d 个回归记录 (%.1f%%)",
        stats[0], stats[1], stats[2],
    )

    return conn.execute(f"SELECT * FROM {view_name}")


def get_regression_summary(
    conn: duckdb.DuckDBPyConnection,
    view_name: str = "judged_dedup",
) -> dict:
    """
    获取 SN 去重后的回归摘要统计。

    Args:
        conn: DuckDB 连接
        view_name: 去重视图名称

    Returns:
        dict: {
            total_unique_sn: int,        # 去重后唯一 SN 数量
            regressed_sn_count: int,     # 存在回归的 SN 数（time > first_time）
            regression_rate_pct: float,  # 回归率百分比
            max_occurrences: int,        # 单个 SN 最大出现次数
        }
    """
    # 检查视图是否存在
    exists = conn.execute(
        "SELECT COUNT(*) FROM information_schema.views WHERE table_name = ?",
        [view_name],
    ).fetchone()[0]

    if not exists:
        logger.warning("视图 %s 不存在，请先执行 apply_regression_rules()", view_name)
        return {
            "total_unique_sn": 0,
            "regressed_sn_count": 0,
            "regression_rate_pct": 0.0,
            "max_occurrences": 0,
        }

    stats = conn.execute(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN time > first_time THEN 1 ELSE 0 END) AS regressed,
            ROUND(
                SUM(CASE WHEN time > first_time THEN 1 ELSE 0 END) * 100.0
                / NULLIF(COUNT(*), 0), 2
            ) AS rate,
            COALESCE(MAX(rn), 0) AS max_occ
        FROM {view_name}
    """).fetchone()

    return {
        "total_unique_sn": int(stats[0]),
        "regressed_sn_count": int(stats[1]),
        "regression_rate_pct": float(stats[2] or 0.0),
        "max_occurrences": int(stats[3]),
    }


def _detect_columns(
    conn: duckdb.DuckDBPyConnection,
    source_pattern: str,
) -> set[str]:
    """
    探测 judged parquet 文件中有哪些列。

    Args:
        conn: DuckDB 连接
        source_pattern: parquet 文件的 glob 模式

    Returns:
        列名集合
    """
    try:
        result = conn.execute(
            f"SELECT column_name FROM parquet_schema('{source_pattern}')"
        ).fetchall()
        return {row[0] for row in result}
    except Exception:
        # parquet_schema 可能不支持 glob，尝试读第一条记录来推断
        try:
            result = conn.execute(
                f"SELECT * FROM read_parquet('{source_pattern}') LIMIT 1"
            ).description
            return {col[0] for col in result}
        except Exception:
            logger.warning("无法探测 judged 数据列信息")
            return set()
