"""
不良 TOP N 分析

对 judged Parquet 中的判定结果列进行逐列统计，
输出 NG 次数最多的 FAI 排名。
"""

from typing import Optional

import pyarrow.parquet as pq
from jinja2 import Template

from src.config import JUDGED_DIR
from src.db import get_connection
from src.aggregator.queries import (
    TOP_DEFECTS_QUERY_TEMPLATE, SINGLE_FAI_ANALYSIS,
    TOP_DEFECTS_DATE_QUERY, DAILY_TOP_DEFECT_TREND,
)


def _get_result_columns(parquet_path: str) -> list[str]:
    """
    获取 Parquet 中所有 result 列名

    Args:
        parquet_path: judged Parquet 文件路径

    Returns:
        以 _result 结尾的列名列表
    """
    pf = pq.ParquetFile(parquet_path)
    cols = [
        field.name for field in pf.schema_arrow
        if field.name.endswith("_result") and field.name != "overall_result"
    ]
    pf.close()
    return cols


def _parquet_glob() -> str:
    """获取 judged Parquet 文件 glob"""
    return str(JUDGED_DIR / "judged_*.parquet")


def get_top_defects(top_n: int = 20) -> list[dict]:
    """
    获取 TOP N 不良 FAI

    Args:
        top_n: 返回前 N 个

    Returns:
        [{fai_name, ng_count, total, ng_rate_pct}, ...] (按 ng_count 降序)
    """
    # 获取第一个 judged 文件的 result 列
    judged_files = sorted(JUDGED_DIR.glob("judged_*.parquet"))
    if not judged_files:
        return []

    result_columns = _get_result_columns(str(judged_files[0]))
    if not result_columns:
        return []

    # 渲染 SQL 模板
    sql = Template(TOP_DEFECTS_QUERY_TEMPLATE).render(
        parquet_glob=_parquet_glob(),
        result_columns=result_columns,
        top_n=top_n,
    )

    rows = get_connection().execute(sql).fetchall()
    return [
        {
            "fai_name": row[0],
            "ng_count": row[1],
            "total": row[2],
            "ng_rate_pct": row[3],
        }
        for row in rows
    ]


def get_top_defects_by_date(
    start_date: str,
    end_date: str,
    top_n: int = 20,
) -> list[dict]:
    """
    获取指定日期范围内的 TOP N 不良 FAI

    Args:
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        top_n: 返回前 N 个

    Returns:
        [{fai_name, ng_count, total, ng_rate_pct}, ...]
    """
    judged_files = sorted(JUDGED_DIR.glob("judged_*.parquet"))
    if not judged_files:
        return []

    result_columns = _get_result_columns(str(judged_files[0]))
    if not result_columns:
        return []

    sql = Template(TOP_DEFECTS_DATE_QUERY).render(
        parquet_glob=_parquet_glob(),
        result_columns=result_columns,
        start_date=start_date,
        end_date=end_date,
        top_n=top_n,
    )

    rows = get_connection().execute(sql).fetchall()
    return [
        {
            "fai_name": row[0],
            "ng_count": row[1],
            "total": row[2],
            "ng_rate_pct": row[3],
        }
        for row in rows
    ]


def get_daily_top_trend(
    top_fai_names: list[str],
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    获取指定 TOP FAI 的每日 NG 趋势

    Args:
        top_fai_names: 要追踪的 FAI 名称列表（最多 10 个）
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        [{production_day, fai1_ng, fai2_ng, ...}, ...]
    """
    judged_files = sorted(JUDGED_DIR.glob("judged_*.parquet"))
    if not judged_files or not top_fai_names:
        return []

    # 构建结果列名
    result_columns = [f"{name}_result" for name in top_fai_names]

    sql = Template(DAILY_TOP_DEFECT_TREND).render(
        parquet_glob=_parquet_glob(),
        result_columns=result_columns,
        start_date=start_date,
        end_date=end_date,
        top_fai_count=len(result_columns),
    )

    rows = get_connection().execute(sql).fetchall()
    if not rows:
        return []

    # 构建返回值
    result = []
    col_names = [desc[0] for desc in get_connection().execute(sql).description]
    for row in rows:
        day_data = {"production_day": str(row[0])}
        for i, name in enumerate(top_fai_names):
            day_data[f"{name}_ng"] = row[i + 1] if row[i + 1] else 0
        result.append(day_data)
    return result


def get_available_date_range() -> tuple[str, str]:
    """获取数据中的日期范围"""
    conn = get_connection()
    row = conn.execute(f"""
        SELECT
            MIN(CAST(TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '7 hours' AS DATE)),
            MAX(CAST(TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '7 hours' AS DATE))
        FROM read_parquet('{_parquet_glob()}', union_by_name=true)
        WHERE "Time" IS NOT NULL
    """).fetchone()
    return (str(row[0]) if row[0] else "", str(row[1]) if row[1] else "")


def get_fai_defect_detail(
    fai_name: str,
    top_n: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """
    获取指定 FAI 的不良明细

    Args:
        fai_name: FAI 名称
        top_n: 返回最多行数

    Returns:
        [{measured_value, result, SN, Time, Line}, ...]
    """
    sql = Template(SINGLE_FAI_ANALYSIS).render(
        parquet_glob=_parquet_glob(),
        fai_name=fai_name,
        fai_result_col=f"{fai_name}_result",
        top_n=top_n,
        start_date=start_date or "",
        end_date=end_date or "",
    )

    rows = get_connection().execute(sql).fetchall()
    return [
        {
            "measured_value": row[0],
            "result": row[1],
            "SN": row[2],
            "Time": str(row[3]) if row[3] else None,
            "Line": row[4],
        }
        for row in rows
    ]



def get_top_defects_regression(
    top_n: int = 20,
    project: Optional[str] = None,
    line: Optional[str] = None,
) -> list[dict]:
    """
    获取回归后 TOP N 不良 FAI (基于回归唯一SN)

    Args:
        top_n: 返回前 N 个
        project: 可选 Project 筛选
        line: 可选 Line 筛选

    Returns:
        [{fai_name, ng_count, total, ng_rate_pct}, ...]
    """
    from src.aggregator.queries import DAILY_TOP_DEFECTS_REGRESSION_QUERY
    from jinja2 import Template
    
    judged_files = sorted(JUDGED_DIR.glob("judged_*.parquet"))
    if not judged_files:
        return []

    result_columns = _get_result_columns(str(judged_files[0]))
    if not result_columns:
        return []

    # Build extra_where
    extra_parts = []
    if project:
        safe = project.replace("'", "''")
        extra_parts.append('"Project" = \'' + safe + '\'')
    if line:
        safe = line.replace("'", "''")
        extra_parts.append('"Line" = \'' + safe + '\'')
    extra_where = " AND ".join(extra_parts) if extra_parts else ""

    sql = Template(DAILY_TOP_DEFECTS_REGRESSION_QUERY).render(
        parquet_glob=_parquet_glob(),
        result_columns=result_columns,
        top_n=top_n,
        cutoff_hour=7,
        extra_where=extra_where,
    )

    rows = get_connection().execute(sql).fetchall()
    # regression query returns per-day data; aggregate across all days
    agg = {}
    for row in rows:
        fai_name = row[1]
        ng_count = row[2]
        total = row[3]
        if fai_name not in agg:
            agg[fai_name] = {"ng_count": 0, "total": 0}
        agg[fai_name]["ng_count"] += ng_count
        agg[fai_name]["total"] += total

    result = [
        {
            "fai_name": name,
            "ng_count": data["ng_count"],
            "total": data["total"],
            "ng_rate_pct": round(data["ng_count"] * 100.0 / max(data["total"], 1), 2),
        }
        for name, data in agg.items()
    ]
    result.sort(key=lambda x: x["ng_count"], reverse=True)
    return result[:top_n]


def get_all_ng_sns_regression(start_date: str, end_date: str) -> "pd.DataFrame":
    """
    获取回归后所有 NG SN 的明细数据 (用于下载)。

    Returns:
        DataFrame with SN, Time, Line, Project, Vendor, overall_result + NG FAI details
    """
    import pandas as pd
    from src.aggregator.regression import get_regression_unique_sn
    
    df = get_regression_unique_sn(
        start_date=start_date, end_date=end_date, columns="all"
    )
    # Filter to NG only
    if "overall_result" in df.columns:
        df = df[df["overall_result"] == 1]
    return df
