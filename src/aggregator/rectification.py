"""
整形良率计算 (Rectification Yield Estimation)

领域词: 整形 (rectification) — NG 物理修复挽回
详见 ADR-0001

职责:
- 维护 FAI 白名单 (哪些 FAI 的 NG 可通过整形挽回)
- 计算可整形的 SN 数和预计挽回量
- 按日汇总预计整形后良率

不在此模块:
- SN 回归逻辑 (regression.py)
- 数据加载 / 仪表盘 (dashboard)
"""

import re
from typing import Optional

from src.config import DAY_CUTOFF_HOUR, JUDGED_DIR
from src.db import get_connection


# 整形白名单 (基础名, 不带后缀)
RECTIFICATION_FAI_BASE: set = {
    "FAI312", "FAI313", "FAI314", "FAI315", "FAI316", "FAI317", "FAI318", "FAI319",
    "FAI320", "FAI321", "FAI322", "FAI323", "FAI324", "FAI325", "FAI326", "FAI327",
    "FAI344", "FAI346", "FAI347", "FAI348",
}

# 整形挽回率 (整批 86%)
RECTIFICATION_SAVE_RATE: float = 0.86


def _is_rectification_fai(fai_name: str) -> bool:
    """
    判断 FAI 是否在整形白名单内。

    规则: 从列名提取 FAI 前缀 (FAI312, FAI313, ...) 后检查是否在白名单中。
    支持各种后缀: _1, _10, _A01_T, 等。
    """
    m = re.match(r"(FAI\d+)", fai_name)
    if m:
        return m.group(1) in RECTIFICATION_FAI_BASE
    return False



def get_fai_base_names() -> list[tuple[str, str]]:
    """
    从 parquet schema 动态获取所有 FAI 列的 (列名, 基础名) 列表。

    Returns:
        [(column_name, base_name), ...] 如 [("FAI312_result", "FAI312"), ...]
    """
    conn = get_connection()
    glob_path = get_default_source().parquet_glob().strip("'")
    schema = conn.execute(f"""
        SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{glob_path}', union_by_name=true) LIMIT 1)
    """).fetchall()
    result = []
    for (col,) in schema:
        if col == "overall_result":
            continue
        if col.endswith("_result"):
            base = col[:-len("_result")]
            result.append((col, base))
    return result


def _build_rectification_conditions() -> tuple[str, str, str]:
    """
    根据 schema 动态构造整形判定用的 SQL 片段。

    Returns:
        (total_ng_expr, out_of_whitelist_expr, glob_path)
        - total_ng_expr: 计算 NG FAI 总数的 SQL 表达式
        - out_of_whitelist_expr: 计算不在白名单的 NG FAI 数量的 SQL 表达式
        - glob_path: parquet 路径
    """
    fai_pairs = get_fai_base_names()  # [(col, base), ...]
    glob_path = get_default_source().parquet_glob().strip("'")

    if not fai_pairs:
        return "0", "0", glob_path

    # 整形白名单的 FAI 基础名集合 (含 _T/_Z 后缀的也会被 _is_rectification_fai 包含)
    whitelist_bases = {base for _, base in fai_pairs if _is_rectification_fai(base)}

    # total_ng_count = 所有 NG FAI 数量
    total_parts = [f'CASE WHEN "{col}" = 1 THEN 1 ELSE 0 END' for col, _ in fai_pairs]
    total_ng_expr = " + ".join(total_parts)

    # out_of_whitelist_count = 不在白名单的 NG FAI 数量
    out_parts = []
    for col, base in fai_pairs:
        if base in whitelist_bases:
            # 在白名单, 不计入 out_of_whitelist
            continue
        out_parts.append(f'CASE WHEN "{col}" = 1 THEN 1 ELSE 0 END')
    out_of_whitelist_expr = " + ".join(out_parts) if out_parts else "0"

    return total_ng_expr, out_of_whitelist_expr, glob_path


def get_rectification_stats(
    cutoff_hour: int = DAY_CUTOFF_HOUR,
    project: Optional[str] = None,
    line: Optional[str] = None,
) -> dict:
    """
    计算预计整形后的良率 (全局)。

    规则 (ADR-0001):
    - 一条 SN 判为 NG
    - 检查其所有 NG 的 FAI 列
    - 如果这些 NG FAI 全部在整形白名单内 → 该 SN "可整形"
    - 预计整形后挽回 = 可整形 SN 数 × 86%

    Args:
        cutoff_hour: 日切点小时
        project: 可选 Project 筛选
        line: 可选 Line 筛选

    Returns:
        {
            total: 总行数,
            ok_count: OK 行数,
            ng_count: NG 行数,
            rectifiable_count: 可整形行数 (其所有 NG FAI 都在白名单内),
            saved_count: 预计挽回数 = rectifiable_count × 86%,
            yield_pct_pre: 原始良率,
            yield_pct_post: 预计整形后良率,
        }
    """
    conn = get_connection()
    total_ng_expr, out_of_whitelist_expr, glob_path = _build_rectification_conditions()

    if total_ng_expr == "0":
        return {
            "total": 0, "ok_count": 0, "ng_count": 0,
            "rectifiable_count": 0, "saved_count": 0,
            "yield_pct_pre": 0, "yield_pct_post": 0,
        }

    # Build extra_where for Project/Line filter
    extra_parts = []
    if project:
        safe = project.replace("'", "''")
        extra_parts.append('"Project" = \'' + safe + '\'')
    if line:
        safe = line.replace("'", "''")
        extra_parts.append('"Line" = \'' + safe + '\'')
    extra_where = " AND ".join(extra_parts)
    extra_where_sql = f" AND {extra_where}" if extra_where else ""

    # 关键 SQL: 对每行, 算 (1) NG FAI 总数 (2) 不在白名单的 NG FAI 数
    # 判可整形: overall_result=1 AND out_of_whitelist=0 AND total_ng>0
    sql = f"""
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY SN
                    ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC
                ) AS rn,
                MIN(TRY_CAST("Time" AS TIMESTAMP)) OVER (PARTITION BY SN) AS first_prod_time
            FROM read_parquet('{glob_path}', union_by_name=true)
            WHERE "Time" IS NOT NULL{extra_where_sql}
        ),
        regression_unique AS (
            SELECT * REPLACE(first_prod_time AS "Time") FROM ranked WHERE rn = 1
        )
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) AS ok_count,
            SUM(CASE WHEN overall_result = 1 THEN 1 ELSE 0 END) AS ng_count,
            SUM(CASE
                WHEN overall_result = 1
                 AND ({out_of_whitelist_expr}) = 0
                 AND ({total_ng_expr}) > 0
                THEN 1 ELSE 0 END) AS rectifiable_count
        FROM regression_unique
    """
    row = conn.execute(sql).fetchone()
    total, ok_count, ng_count, rectifiable_count = row

    saved_count = int(rectifiable_count * RECTIFICATION_SAVE_RATE)
    yield_pct_pre = round(ok_count / total * 100, 2) if total > 0 else 0
    yield_pct_post = round((ok_count + saved_count) / total * 100, 2) if total > 0 else 0

    return {
        "total": total,
        "ok_count": ok_count,
        "ng_count": ng_count,
        "rectifiable_count": rectifiable_count,
        "saved_count": saved_count,
        "yield_pct_pre": yield_pct_pre,
        "yield_pct_post": yield_pct_post,
    }


def get_daily_rectification_yield(
    cutoff_hour: int = DAY_CUTOFF_HOUR,
    project: Optional[str] = None,
    line: Optional[str] = None,
) -> list[dict]:
    """
    按日计算预计整形后良率 (回归前 + 回归后预计整形)。

    Args:
        cutoff_hour: 日切点小时
        project: 可选 Project 筛选
        line: 可选 Line 筛选

    Returns:
        [
            {
                production_day: date,
                total, ok_count, ng_count,
                rectifiable_count, saved_count,
                yield_pct_pre, yield_pct_post,
            }
        ]
    """
    conn = get_connection()
    total_ng_expr, out_of_whitelist_expr, glob_path = _build_rectification_conditions()

    if total_ng_expr == "0":
        return []

    # Build extra_where for Project/Line filter
    extra_parts = []
    if project:
        safe = project.replace("'", "''")
        extra_parts.append('"Project" = \'' + safe + '\'')
    if line:
        safe = line.replace("'", "''")
        extra_parts.append('"Line" = \'' + safe + '\'')
    extra_where = " AND ".join(extra_parts)
    extra_where_sql = f" AND {extra_where}" if extra_where else ""

    # 按日汇总（基于回归后唯一 SN）
    sql = f"""
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY SN
                    ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC
                ) AS rn,
                MIN(TRY_CAST("Time" AS TIMESTAMP)) OVER (PARTITION BY SN) AS first_prod_time
            FROM read_parquet('{glob_path}', union_by_name=true)
            WHERE "Time" IS NOT NULL
              AND TRY_CAST("Time" AS TIMESTAMP) IS NOT NULL{extra_where_sql}
        ),
        regression_unique AS (
            SELECT * REPLACE(first_prod_time AS "Time") FROM ranked WHERE rn = 1
        )
        SELECT
            CAST(TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '{cutoff_hour}' hours AS DATE) as day,
            COUNT(*) as total,
            SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) as ok_count,
            SUM(CASE WHEN overall_result = 1 THEN 1 ELSE 0 END) as ng_count,
            SUM(CASE
                WHEN overall_result = 1
                 AND ({out_of_whitelist_expr}) = 0
                 AND ({total_ng_expr}) > 0
                THEN 1 ELSE 0 END) as rectifiable_count
        FROM regression_unique
        GROUP BY day
        ORDER BY day
    """
    rows = conn.execute(sql).fetchall()
    return [
        {
            "production_day": str(r[0]),
            "total": r[1],
            "ok_count": r[2],
            "ng_count": r[3],
            "rectifiable_count": r[4],
            "saved_count": int(r[4] * RECTIFICATION_SAVE_RATE),
            "yield_pct_pre": round(r[2] / r[1] * 100, 2) if r[1] > 0 else 0,
            "yield_pct_post": round((r[2] + int(r[4] * RECTIFICATION_SAVE_RATE)) / r[1] * 100, 2) if r[1] > 0 else 0,
        }
        for r in rows
    ]
