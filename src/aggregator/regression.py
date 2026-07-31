"""
SN 回归分析 (Regress to first Time, last measurement)

实现同一 SN 多次投产时的回归统计规则:
- 取最后一次投产数据 (末次测量结果)
- 回归到第一次投产时间上进行统计 (首次 Time)

模块分工:
- 本文件: DuckDB SQL 适配 (thin glue)
- src.aggregator.dedup: 纯去重逻辑 (latest_per_sn, first_per_sn)
  → 100% 单元测试覆盖, 无 DuckDB 依赖

不在此模块:
- 整形良率 (rectification) — 已在 src.aggregator.rectification
- 原始数据下载 (rawdata) — 仍在 _build_unique_sn_query 等函数中
"""

from typing import Optional

from jinja2 import Template

from src.config import DAY_CUTOFF_HOUR, JUDGED_DIR
from src.db import get_connection
from src.aggregator.data_source import get_default_source
from src.aggregator.queries import SN_REGRESSION_QUERY, SN_MULTI_PRODUCTION_QUERY



def get_regression_daily(
    cutoff_hour: int = DAY_CUTOFF_HOUR,
    cfg: Optional[str] = None,
) -> list[dict]:
    """
    获取 SN 回归后的按日良率

    规则：同一 SN 取最新投产数据，按首次投产时间归属统计日

    Args:
        cutoff_hour: 日切点小时
        cfg: 可选的 Line 筛选

    Returns:
        [{production_day, total, ok_count, yield_pct}, ...]
    """
    sql = Template(SN_REGRESSION_QUERY).render(
        parquet_glob=get_default_source().parquet_glob().strip("'"),
        cutoff_hour=cutoff_hour,
    )

    rows = get_connection().execute(sql).fetchall()
    return [
        {
            "production_day": str(row[0]),
            "total": row[1],
            "ok_count": row[2],
            "yield_pct": row[3],
        }
        for row in rows
    ]


def get_duplicate_sn_count() -> int:
    """
    获取有多次投产记录的 SN 数量

    Returns:
        多次投产的 SN 数量
    """
    sql = f"""
        SELECT COUNT(*) FROM (
            SELECT SN, COUNT(*) as cnt
            FROM read_parquet({get_default_source().parquet_glob()}, union_by_name=true)
            GROUP BY SN
            HAVING cnt > 1
        )
    """
    return get_connection().execute(sql).fetchone()[0]


def get_regression_summary() -> dict:
    """
    获取回归分析摘要

    Returns:
        {
            total_sn: 总 SN 数量,
            duplicate_sn: 有重复投产的 SN 数量,
            max_productions: 单个 SN 最多投产次数,
            duplicate_rate_pct: SN 重复率
        }
    """
    conn = get_connection()

    total_sn = conn.execute(f"""
        SELECT COUNT(DISTINCT SN) FROM read_parquet({get_default_source().parquet_glob()}, union_by_name=true)
    """).fetchone()[0]

    dup_sn = conn.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT SN FROM read_parquet({get_default_source().parquet_glob()}, union_by_name=true)
            GROUP BY SN HAVING COUNT(*) > 1
        )
    """).fetchone()[0]

    max_prod = conn.execute(f"""
        SELECT MAX(cnt) FROM (
            SELECT COUNT(*) as cnt FROM read_parquet({get_default_source().parquet_glob()}, union_by_name=true)
            GROUP BY SN
        )
    """).fetchone()[0] or 1

    return {
        "total_sn": total_sn,
        "duplicate_sn": dup_sn,
        "max_productions": max_prod,
        "duplicate_rate_pct": round(dup_sn / total_sn * 100, 2) if total_sn > 0 else 0,
    }


# ═══════════════════════════════════════════════════════════════
# 回归后的唯一 SN Rawdata 下载
# ═══════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# 回归后唯一 SN 查询（统一接口）
# ═══════════════════════════════════════════════════════════════



def get_regression_unique_sn_count() -> dict:
    """
    获取回归去重前后 SN 数对比。

    Returns:
        {
            total_rows: 总记录数,
            unique_sn: 去重后唯一 SN 数,
            duplicate_rows: 因回归被丢弃的重复记录数,
            dedup_ratio_pct: 去重比例,
        }
    """
    sql = f"""
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY SN
                    ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC
                ) AS rn
            FROM read_parquet({get_default_source().parquet_glob()}, union_by_name=true)
        )
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN rn = 1 THEN 1 ELSE 0 END) AS unique_sn,
            SUM(CASE WHEN rn > 1 THEN 1 ELSE 0 END) AS duplicate_rows
        FROM ranked
    """
    row = get_connection().execute(sql).fetchone()
    total, unique, dup = row[0], row[1], row[2]
    return {
        "total_rows": total,
        "unique_sn": unique,
        "duplicate_rows": dup,
        "dedup_ratio_pct": round(dup / total * 100, 2) if total > 0 else 0,
    }


def _build_unique_sn_query(
    columns: str = "core",
    cfg: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    构造回归去重后的唯一 SN 查询 SQL。

    Args:
        columns: "core" = 7 个关键列（轻量, 0.1s）; "all" = 全列（1364列, ~4s）
        cfg: 可选的 Line 精确筛选
        start_date, end_date: 日期范围筛选 (YYYY-MM-DD, end_date 含当天)
    """
    where_clauses = []
    if cfg:
        safe_cfg = cfg.replace("'", "''")
        where_clauses.append(f'\"Line\" = \'{safe_cfg}\'')
    if start_date:
        safe_start = start_date.replace("'", "''")
        where_clauses.append(f'TRY_CAST("Time" AS TIMESTAMP) >= \'{safe_start}\'')
    if end_date:
        safe_end = end_date.replace("'", "''")
        where_clauses.append(
            f"TRY_CAST(\"Time\" AS TIMESTAMP) < "
            f"CAST('{safe_end}' AS DATE) + INTERVAL '1 day'"
        )
    extra_where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    select_clause = (
        "*" if columns == "all"
        else 'SN, "Line", "Time", "Project", "Vendor", "Yield3", "overall_result"'
    )

    return f"""
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY SN
                    ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC
                ) AS rn,
                MIN(TRY_CAST("Time" AS TIMESTAMP)) OVER (PARTITION BY SN) AS first_prod_time
            FROM read_parquet({get_default_source().parquet_glob()}, union_by_name=true)
            {extra_where}
        ),
        latest_only AS (
            SELECT * REPLACE(first_prod_time AS "Time") FROM ranked WHERE rn = 1
        )
        SELECT {select_clause}
        FROM latest_only
        ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC
    """


def get_regression_unique_sn(
    cfg: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    columns: str = "core",
) -> "pd.DataFrame":
    """
    获取回归后唯一 SN 的数据（统一入口）。

    Args:
        cfg: 可选的 Line 精确筛选。
        start_date, end_date: 日期范围 (YYYY-MM-DD)。
        columns: "core" = 7 列轻量, "all" = 全列。

    Returns:
        pd.DataFrame
    """
    import pandas as pd

    sql = _build_unique_sn_query(columns, cfg, start_date, end_date)
    df = get_connection().execute(sql).fetchdf()
    if "Time" in df.columns:
        df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    return df


# ────────────────────────────────────────────────────────
# 向后兼容：旧名字保持可调用
# ────────────────────────────────────────────────────────


def get_regression_unique_sn_fast(
    cfg: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    full_columns: bool = False,
) -> "pd.DataFrame":
    """向后兼容：旧 fast 接口，转发到 get_regression_unique_sn。"""
    return get_regression_unique_sn(
        cfg=cfg,
        start_date=start_date,
        end_date=end_date,
        columns="all" if full_columns else "core",
    )


def get_regression_unique_sn_rawdata(
    cfg: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> "pd.DataFrame":
    """向后兼容：旧 rawdata 接口 = 全部列。"""
    return get_regression_unique_sn(
        cfg=cfg, start_date=start_date, end_date=end_date, columns="all"
    )




# ════════════════════════════════════════════════════════════
# 向后兼容: 整形函数 re-export
# (原在 regression.py, 现已迁出到 src.aggregator.rectification)
# ════════════════════════════════════════════════════════════

from src.aggregator.rectification import (  # noqa: E402,F401
    RECTIFICATION_FAI_BASE,
    RECTIFICATION_SAVE_RATE,
    get_rectification_stats,
    get_daily_rectification_yield,
    get_fai_base_names,
    _is_rectification_fai,
    _build_rectification_conditions,
)
