"""
良率计算封装

提供高层 API，封装 DuckDB 查询细节。
"""

from typing import Optional

from jinja2 import Template

from src.config import DAY_CUTOFF_HOUR, JUDGED_DIR
from src.db import get_connection
from src.aggregator.queries import (
    SUMMARY_QUERY, DAILY_YIELD_QUERY, WEEKLY_YIELD_QUERY,
    LINE_YIELD_QUERY, SN_REGRESSION_QUERY, SN_MULTI_PRODUCTION_QUERY, VENDOR_YIELD_QUERY,
)


def _render_sql(template: str, **kwargs) -> str:
    """渲染 Jinja2 SQL 模板"""
    return Template(template).render(**kwargs)


def _parquet_glob() -> str:
    """获取 judged Parquet 文件 glob"""
    return str(JUDGED_DIR / "judged_*.parquet")


def get_summary(cfg: Optional[str] = None) -> dict:
    """
    获取总体良率汇总

    Args:
        cfg: 可选的 Line 筛选

    Returns:
        {total, ok_count, ng_count, yield_pct}
    """
    sql = _render_sql(
        SUMMARY_QUERY,
        parquet_glob=_parquet_glob(),
        cfg_filter=cfg,
    )
    row = get_connection().execute(sql).fetchone()
    return {
        "total": row[0],
        "ok_count": row[1],
        "ng_count": row[2],
        "yield_pct": row[3],
    }


def get_daily_yield(
    cfg: Optional[str] = None,
    cutoff_hour: int = DAY_CUTOFF_HOUR,
) -> list[dict]:
    """
    获取按日良率趋势

    Args:
        cfg: 可选的 Line 筛选
        cutoff_hour: 日切点小时（默认 7:00）

    Returns:
        [{production_day, total, ok_count, ng_count, yield_pct}, ...]
    """
    sql = _render_sql(
        DAILY_YIELD_QUERY,
        parquet_glob=_parquet_glob(),
        cutoff_hour=cutoff_hour,
        cfg_filter=cfg,
    )
    rows = get_connection().execute(sql).fetchall()
    return [
        {
            "production_day": str(row[0]),
            "total": row[1],
            "ok_count": row[2],
            "ng_count": row[3],
            "yield_pct": row[4],
        }
        for row in rows
    ]


def get_weekly_yield(
    cfg: Optional[str] = None,
    cutoff_hour: int = DAY_CUTOFF_HOUR,
) -> list[dict]:
    """
    获取按周良率趋势

    Args:
        cfg: 可选的 Line 筛选
        cutoff_hour: 日切点小时

    Returns:
        [{production_week, total, ok_count, yield_pct}, ...]
    """
    sql = _render_sql(
        WEEKLY_YIELD_QUERY,
        parquet_glob=_parquet_glob(),
        cutoff_hour=cutoff_hour,
        cfg_filter=cfg,
    )
    rows = get_connection().execute(sql).fetchall()
    return [
        {
            "production_week": str(row[0]),
            "total": row[1],
            "ok_count": row[2],
            "yield_pct": row[3],
        }
        for row in rows
    ]


def get_cfg_yield() -> list[dict]:
    """获取按 Line 分组的良率"""
    sql = _render_sql(LINE_YIELD_QUERY, parquet_glob=_parquet_glob())
    rows = get_connection().execute(sql).fetchall()
    return [
        {"cfg": row[0], "total": row[1], "ok_count": row[2], "yield_pct": row[3]}
        for row in rows
    ]


def get_vendor_yield() -> list[dict]:
    """获取按 Vendor 分组的良率"""
    sql = _render_sql(VENDOR_YIELD_QUERY, parquet_glob=_parquet_glob())
    rows = get_connection().execute(sql).fetchall()
    return [
        {"vendor": row[0], "total": row[1], "ok_count": row[2], "yield_pct": row[3]}
        for row in rows
    ]


def get_regression_yield(cutoff_hour: int = DAY_CUTOFF_HOUR) -> list[dict]:
    """
    获取 SN 回归后的良率（取最新数据，归入首次投产日）

    Args:
        cutoff_hour: 日切点小时

    Returns:
        [{production_day, total, ok_count, yield_pct}, ...]
    """
    sql = _render_sql(
        SN_REGRESSION_QUERY,
        parquet_glob=_parquet_glob(),
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


def get_multi_production_sns(top_n: int = 20) -> list[dict]:
    """
    获取多次投产的 SN 列表

    Args:
        top_n: 返回前 N 条

    Returns:
        [{SN, production_count, first_time, latest_time}, ...]
    """
    sql = _render_sql(
        SN_MULTI_PRODUCTION_QUERY, VENDOR_YIELD_QUERY,
        parquet_glob=_parquet_glob(),
        top_n=top_n,
    )
    rows = get_connection().execute(sql).fetchall()
    return [
        {
            "SN": row[0],
            "production_count": row[1],
            "first_time": str(row[2]) if row[2] else None,
            "latest_time": str(row[3]) if row[3] else None,
        }
        for row in rows
    ]

def get_daily_yield_by_project_line(
    project: Optional[str] = None,
    line: Optional[str] = None,
    regression: bool = True,
    cutoff_hour: int = DAY_CUTOFF_HOUR,
) -> list[dict]:
    """
    按 Project + Line 分组的每日良率 (用于多线体对比图)。

    Args:
        project: 可选 Project 筛选 (None=全部)
        line: 可选 Line 筛选 (None=全部)
        regression: True=回归后, False=回归前
        cutoff_hour: 日切点

    Returns:
        [{production_day, project, line, total, ok_count, ng_count, yield_pct}, ...]
    """
    conn = get_connection()
    where_clauses = ['"Time" IS NOT NULL']
    if project:
        safe_p = project.replace("'", "''")
        where_clauses.append(f'\"Project\" = \'{safe_p}\'')
    if line:
        safe_l = line.replace("'", "''")
        where_clauses.append(f'\"Line\" = \'{safe_l}\'')
    where_sql = " AND ".join(where_clauses)

    if regression:
        # 回归: 同一 SN, 取首次 Time + 末次测量结果
        sql = f"""
            WITH ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY SN
                        ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC
                    ) AS rn
                FROM read_parquet('{_parquet_glob()}', union_by_name=true)
                WHERE {where_sql}
            )
            SELECT
                CAST(TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '{cutoff_hour}' hours AS DATE) as day,
                "Project",
                "Line",
                COUNT(*) as total,
                SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) as ok_count
            FROM ranked
            WHERE rn = 1
            GROUP BY day, "Project", "Line"
            ORDER BY day
        """
    else:
        sql = f"""
            SELECT
                CAST(TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '{cutoff_hour}' hours AS DATE) as day,
                "Project",
                "Line",
                COUNT(*) as total,
                SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) as ok_count
            FROM read_parquet('{_parquet_glob()}', union_by_name=true)
            WHERE {where_sql}
            GROUP BY day, "Project", "Line"
            ORDER BY day
        """
    rows = conn.execute(sql).fetchall()
    return [
        {
            "production_day": str(r[0]),
            "project": str(r[1]) if r[1] else "未知",
            "line": str(r[2]) if r[2] else "未知",
            "total": r[3],
            "ok_count": r[4],
            "ng_count": r[3] - r[4],
            "yield_pct": round(r[4] / r[3] * 100, 2) if r[3] > 0 else 0,
        }
        for r in rows
    ]


def list_projects() -> list[str]:
    """获取所有出现过的 Project 名称列表"""
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT DISTINCT "Project" FROM read_parquet('{_parquet_glob()}', union_by_name=true)
        WHERE "Project" IS NOT NULL
        ORDER BY "Project"
    """).fetchall()
    return [r[0] for r in rows if r[0]]


def list_lines_for_project(project: str) -> list[str]:
    """获取某 Project 下所有出现过的 Line 名称"""
    conn = get_connection()
    safe_p = project.replace("'", "''")
    rows = conn.execute(f"""
        SELECT DISTINCT "Line" FROM read_parquet('{_parquet_glob()}', union_by_name=true)
        WHERE "Project" = '{safe_p}' AND "Line" IS NOT NULL
        ORDER BY "Line"
    """).fetchall()
    return [r[0] for r in rows if r[0]]

