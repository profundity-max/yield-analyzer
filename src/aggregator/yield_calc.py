"""
良率计算封装

提供高层 API，封装 DuckDB 查询细节。

使用 YieldQuery deep module 把"渲染 SQL → 执行 → 转 dict"统一处理。
本文件只声明 QuerySpec + 1 行调用, 不再是浅 wrapper。
"""

from typing import Optional

from src.config import DAY_CUTOFF_HOUR
from src.aggregator.queries import (
    SUMMARY_QUERY, DAILY_YIELD_QUERY, WEEKLY_YIELD_QUERY,
    LINE_YIELD_QUERY, VENDOR_YIELD_QUERY, SN_REGRESSION_QUERY,
    SN_MULTI_PRODUCTION_QUERY,
)
from src.aggregator.data_source import get_default_source
from src.aggregator.yield_query import (
    YieldQuery, QuerySpec, get_default_query,
)


# ════════════════════════════════════════════════════════════
# Row mappers (纯函数, 1 行可测)
# ════════════════════════════════════════════════════════════


def _summary_mapper(row: tuple) -> dict:
    return {
        "total": row[0],
        "ok_count": row[1],
        "ng_count": row[2],
        "yield_pct": row[3],
    }


def _daily_yield_mapper(row: tuple) -> dict:
    return {
        "production_day": str(row[0]),
        "total": row[1],
        "ok_count": row[2],
        "ng_count": row[3],
        "yield_pct": row[4],
    }


def _weekly_yield_mapper(row: tuple) -> dict:
    return {
        "production_week": str(row[0]),
        "total": row[1],
        "ok_count": row[2],
        "yield_pct": row[3],
    }


def _line_yield_mapper(row: tuple) -> dict:
    return {
        "line": str(row[0]),
        "total": row[1],
        "ok_count": row[2],
        "yield_pct": row[3],
    }


def _vendor_yield_mapper(row: tuple) -> dict:
    return {
        "vendor": str(row[0]),
        "total": row[1],
        "ok_count": row[2],
        "yield_pct": row[3],
    }


def _multi_production_mapper(row: tuple) -> dict:
    return {
        "SN": row[0],
        "production_count": row[1],
        "first_time": str(row[2]) if row[2] else None,
        "latest_time": str(row[3]) if row[3] else None,
    }


# ════════════════════════════════════════════════════════════
# QuerySpecs (声明: 哪个模板 + 怎么转 row)
# ════════════════════════════════════════════════════════════


_SUMMARY_SPEC = QuerySpec("SUMMARY_QUERY", _summary_mapper)
_DAILY_YIELD_SPEC = QuerySpec("DAILY_YIELD_QUERY", _daily_yield_mapper)
_WEEKLY_YIELD_SPEC = QuerySpec("WEEKLY_YIELD_QUERY", _weekly_yield_mapper)
_LINE_YIELD_SPEC = QuerySpec("LINE_YIELD_QUERY", _line_yield_mapper)
_VENDOR_YIELD_SPEC = QuerySpec("VENDOR_YIELD_QUERY", _vendor_yield_mapper)
_MULTI_PROD_SPEC = QuerySpec(
    "SN_MULTI_PRODUCTION_QUERY", _multi_production_mapper,
    extra_context={"top_n": 20},
)


# ════════════════════════════════════════════════════════════
# Public API (每条都是 1 行调用)
# ════════════════════════════════════════════════════════════


def get_summary(cfg: Optional[str] = None) -> dict:
    """获取总体良率汇总。删除测试通过: 删掉它, 复杂度只迁移到 QuerySpec。"""
    from src.aggregator.data_source import Filters
    return get_default_query().fetch_one(
        _SUMMARY_SPEC,
        filters=Filters() if cfg is None else None,
    ) or {"total": 0, "ok_count": 0, "ng_count": 0, "yield_pct": 0}


def get_daily_yield(
    cfg: Optional[str] = None,
    cutoff_hour: int = DAY_CUTOFF_HOUR,
) -> list[dict]:
    """获取按日良率趋势。"""
    spec = QuerySpec(
        "DAILY_YIELD_QUERY", _daily_yield_mapper,
        extra_context={"cutoff_hour": cutoff_hour, "cfg_filter": cfg},
    )
    return get_default_query().fetch_all(spec)


def get_weekly_yield(
    cfg: Optional[str] = None,
    cutoff_hour: int = DAY_CUTOFF_HOUR,
) -> list[dict]:
    """获取按周良率趋势。"""
    spec = QuerySpec(
        "WEEKLY_YIELD_QUERY", _weekly_yield_mapper,
        extra_context={"cutoff_hour": cutoff_hour, "cfg_filter": cfg},
    )
    return get_default_query().fetch_all(spec)


def get_cfg_yield() -> list[dict]:
    """获取按 Line 分组的良率。"""
    return get_default_query().fetch_all(_LINE_YIELD_SPEC)


def get_vendor_yield() -> list[dict]:
    """获取按 Vendor 分组的良率。"""
    return get_default_query().fetch_all(_VENDOR_YIELD_SPEC)


def get_regression_yield(cutoff_hour: int = DAY_CUTOFF_HOUR) -> list[dict]:
    """获取回归后良率 (按日)。"""
    spec = QuerySpec(
        "SN_REGRESSION_QUERY", _daily_yield_mapper,
        extra_context={"cutoff_hour": cutoff_hour},
    )
    return get_default_query().fetch_all(spec)


def get_multi_production_sns(top_n: int = 20) -> list[dict]:
    """获取多次投产的 SN 列表。"""
    spec = QuerySpec(
        "SN_MULTI_PRODUCTION_QUERY", _multi_production_mapper,
        extra_context={"top_n": top_n},
    )
    return get_default_query().fetch_all(spec)


# ════════════════════════════════════════════════════════════
# 仍保留的复杂查询 (inline SQL, 暂不抽象)
# 这些是 ad-hoc 查询, 不在 deletion test 范围内
# ════════════════════════════════════════════════════════════


def get_daily_yield_by_project_line(
    project: Optional[str] = None,
    line: Optional[str] = None,
    regression: bool = True,
    cutoff_hour: int = DAY_CUTOFF_HOUR,
) -> list[dict]:
    """
    按 Project + Line 分组的每日良率 (用于多线体对比图)。
    inline SQL, 因 group by 组合多样, 暂未抽象到 QuerySpec。
    """
    from src.db import get_connection
    from src.aggregator.schema import YieldSchema

    conn = get_connection()
    where_clauses = [f'"{YieldSchema.TIME}" IS NOT NULL']
    if project:
        safe_p = project.replace("'", "''")
        where_clauses.append(f'"{YieldSchema.PROJECT}" = \'{safe_p}\'')
    if line:
        safe_l = line.replace("'", "''")
        where_clauses.append(f'"{YieldSchema.LINE}" = \'{safe_l}\'')
    where_sql = " AND ".join(where_clauses)
    glob = get_default_source().parquet_glob()

    if regression:
        # 回归: 同一 SN, 取首次 Time + 末次测量结果
        sql = f"""
            WITH ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY "{YieldSchema.SN}"
                        ORDER BY TRY_CAST("{YieldSchema.TIME}" AS TIMESTAMP) DESC
                    ) AS rn
                FROM read_parquet({glob}, union_by_name=true)
                WHERE {where_sql}
            )
            SELECT
                CAST(TRY_CAST("{YieldSchema.TIME}" AS TIMESTAMP) - INTERVAL '{cutoff_hour}' hours AS DATE) as day,
                "{YieldSchema.PROJECT}",
                "{YieldSchema.LINE}",
                COUNT(*) as total,
                SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) as ok_count
            FROM ranked
            WHERE rn = 1
            GROUP BY day, "{YieldSchema.PROJECT}", "{YieldSchema.LINE}"
            ORDER BY day
        """
    else:
        sql = f"""
            SELECT
                CAST(TRY_CAST("{YieldSchema.TIME}" AS TIMESTAMP) - INTERVAL '{cutoff_hour}' hours AS DATE) as day,
                "{YieldSchema.PROJECT}",
                "{YieldSchema.LINE}",
                COUNT(*) as total,
                SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) as ok_count
            FROM read_parquet({glob}, union_by_name=true)
            WHERE {where_sql}
            GROUP BY day, "{YieldSchema.PROJECT}", "{YieldSchema.LINE}"
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
    """获取所有出现过的 Project 名称列表。"""
    from src.db import get_connection
    from src.aggregator.schema import YieldSchema

    glob = get_default_source().parquet_glob()
    rows = get_connection().execute(f"""
        SELECT DISTINCT "{YieldSchema.PROJECT}" FROM read_parquet({glob}, union_by_name=true)
        WHERE "{YieldSchema.PROJECT}" IS NOT NULL
        ORDER BY "{YieldSchema.PROJECT}"
    """).fetchall()
    return [r[0] for r in rows if r[0]]


def list_lines_for_project(project: str) -> list[str]:
    """获取某 Project 下所有出现过的 Line 名称。"""
    from src.db import get_connection
    from src.aggregator.schema import YieldSchema

    glob = get_default_source().parquet_glob()
    safe_p = project.replace("'", "''")
    rows = get_connection().execute(f"""
        SELECT DISTINCT "{YieldSchema.LINE}" FROM read_parquet({glob}, union_by_name=true)
        WHERE "{YieldSchema.PROJECT}" = '{safe_p}' AND "{YieldSchema.LINE}" IS NOT NULL
        ORDER BY "{YieldSchema.LINE}"
    """).fetchall()
    return [r[0] for r in rows if r[0]]
