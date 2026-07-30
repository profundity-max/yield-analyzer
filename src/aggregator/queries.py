"""
DuckDB SQL 查询模板

所有聚合分析的 SQL 查询集中管理，使用 Jinja2 模板支持参数化。
"""

# ── 基础良率查询 ─────────────────────────────────────────

SUMMARY_QUERY = """
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) AS ok_count,
    SUM(CASE WHEN overall_result = 1 THEN 1 ELSE 0 END) AS ng_count,
    ROUND(SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS yield_pct
FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
{% if cfg_filter %}
WHERE "Line" = '{{ cfg_filter }}'
{% endif %}
"""

# ── 按日良率（带日切点偏移） ──────────────────────────────

DAILY_YIELD_QUERY = """
WITH shifted AS (
    SELECT *,
        TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '{{ cutoff_hour }} hours' AS shifted_time
    FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
    WHERE "Time" IS NOT NULL
      AND TRY_CAST("Time" AS TIMESTAMP) IS NOT NULL
      {% if extra_where %} AND {{ extra_where }} {% endif %}
)
SELECT
    CAST(shifted_time AS DATE) AS production_day,
    COUNT(*) AS total,
    SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) AS ok_count,
    SUM(CASE WHEN overall_result = 1 THEN 1 ELSE 0 END) AS ng_count,
    ROUND(SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS yield_pct
FROM shifted
GROUP BY production_day
ORDER BY production_day
"""

# ── 按周良率 ─────────────────────────────────────────────

WEEKLY_YIELD_QUERY = """
WITH shifted AS (
    SELECT *,
        TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '{{ cutoff_hour }} hours' AS shifted_time
    FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
    WHERE "Time" IS NOT NULL
      AND TRY_CAST("Time" AS TIMESTAMP) IS NOT NULL
)
SELECT
    DATE_TRUNC('week', shifted_time) AS production_week,
    COUNT(*) AS total,
    SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) AS ok_count,
    ROUND(SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS yield_pct
FROM shifted
{% if cfg_filter %}
WHERE "Line" = '{{ cfg_filter }}'
{% endif %}
GROUP BY production_week
ORDER BY production_week
"""

# ── 按 Line 良率 ───────────────────────────────────────────

LINE_YIELD_QUERY = """
SELECT
    "Line",
    COUNT(*) AS total,
    SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) AS ok_count,
    ROUND(SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS yield_pct
FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
GROUP BY "Line"
ORDER BY yield_pct ASC
"""

# ── TOP N 不良（日期筛选版） ───────────────────────────

TOP_DEFECTS_DATE_QUERY = """
WITH filtered AS (
    SELECT * FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
    WHERE TRY_CAST("Time" AS TIMESTAMP) >= '{{ start_date }}'
      AND TRY_CAST("Time" AS TIMESTAMP) < CAST('{{ end_date }}' AS DATE) + INTERVAL '1 day'
),
fai_stats AS (
    {% for col in result_columns %}
    SELECT '{{ col.replace("_result", "") }}' AS fai_name,
           SUM("{{ col }}") AS ng_count,
           COUNT(*) AS total
    FROM filtered
    {% if not loop.last %}UNION ALL{% endif %}
    {% endfor %}
)
SELECT
    fai_name,
    ng_count,
    total,
    ROUND(ng_count * 100.0 / NULLIF(total, 0), 2) AS ng_rate_pct
FROM fai_stats
WHERE ng_count > 0
ORDER BY ng_count DESC
LIMIT {{ top_n }}
"""

# ── 按日 TOP 不良趋势 ─────────────────────────────────

DAILY_TOP_DEFECT_TREND = """
WITH daily_data AS (
    SELECT
        CAST(TRY_CAST("Time" AS TIMESTAMP) AS DATE) AS production_day,
        {% for col in result_columns[:top_fai_count] %}
        SUM("{{ col }}") AS "{{ col.replace('_result', '') }}_ng"
        {% if not loop.last %},{% endif %}
        {% endfor %}
    FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
    WHERE TRY_CAST("Time" AS TIMESTAMP) >= '{{ start_date }}'
      AND TRY_CAST("Time" AS TIMESTAMP) < CAST('{{ end_date }}' AS DATE) + INTERVAL '1 day'
    GROUP BY production_day
)
SELECT * FROM daily_data
ORDER BY production_day
"""

TOP_DEFECTS_QUERY_TEMPLATE = """
WITH unpivot_data AS (
    SELECT * FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
),
fai_stats AS (
    {% for col in result_columns %}
    SELECT '{{ col.replace("_result", "") }}' AS fai_name,
           SUM("{{ col }}") AS ng_count,
           COUNT(*) AS total
    FROM unpivot_data
    {% if not loop.last %}UNION ALL{% endif %}
    {% endfor %}
)
SELECT
    fai_name,
    ng_count,
    total,
    ROUND(ng_count * 100.0 / total, 2) AS ng_rate_pct
FROM fai_stats
WHERE ng_count > 0
ORDER BY ng_count DESC
LIMIT {{ top_n }}
"""

# ── SN 回归查询（同一SN多次投产） ─────────────────────────

SN_REGRESSION_QUERY = """
WITH ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY SN ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC) AS rn,
        MIN(TRY_CAST("Time" AS TIMESTAMP)) OVER (PARTITION BY SN) AS first_prod_time
    FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
    WHERE "Time" IS NOT NULL
    {% if extra_where %} AND {{ extra_where }} {% endif %}
),
latest_only AS (
    SELECT * FROM ranked WHERE rn = 1
)
SELECT
    CAST(first_prod_time - INTERVAL '{{ cutoff_hour }} hours' AS DATE) AS production_day,
    COUNT(*) AS total,
    SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) AS ok_count,
    ROUND(SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS yield_pct
FROM latest_only
GROUP BY production_day
ORDER BY production_day
"""

# ── SN 多次投产明细 ───────────────────────────────────────

SN_MULTI_PRODUCTION_QUERY = """
WITH prod_count AS (
    SELECT
        SN,
        COUNT(*) AS production_count,
        MIN("Time") AS first_time,
        MAX("Time") AS latest_time
    FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
    WHERE "Time" IS NOT NULL
    GROUP BY SN
)
SELECT * FROM prod_count
WHERE production_count > 1
ORDER BY production_count DESC
LIMIT {{ top_n }}
"""

# ── 单 FAI 详尽分析 ───────────────────────────────────────

SINGLE_FAI_ANALYSIS = """
SELECT
    "{{ fai_name }}" AS measured_value,
    "{{ fai_result_col }}" AS result,
    SN,
    "Time",
    "Line"
FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
WHERE "{{ fai_result_col }}" = 1
{% if start_date and end_date %}
  AND TRY_CAST("Time" AS TIMESTAMP) >= '{{ start_date }}'
  AND TRY_CAST("Time" AS TIMESTAMP) < CAST('{{ end_date }}' AS DATE) + INTERVAL '1 day'
{% endif %}
ORDER BY "Time" DESC
LIMIT {{ top_n }}
"""

# ── 每日 TOP N 不良（回归前） ───────────────────────────

DAILY_TOP_DEFECTS_QUERY = """
WITH daily_data AS (
    SELECT COLUMNS('.*_result'),
        CAST(TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '{{ cutoff_hour }} hours' AS DATE) AS production_day
    FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
    WHERE "Time" IS NOT NULL
      AND TRY_CAST("Time" AS TIMESTAMP) IS NOT NULL
      {% if extra_where %} AND {{ extra_where }} {% endif %}
),
unpivoted AS (
    UNPIVOT daily_data
    ON * EXCLUDE (production_day)
    INTO NAME fai_result_col VALUE ng_flag
),
fai_stats AS (
    SELECT
        production_day,
        REPLACE(fai_result_col, '_result', '') AS fai_name,
        SUM(ng_flag) AS ng_count,
        COUNT(*) AS total
    FROM unpivoted
    WHERE fai_result_col != 'overall_result'
    GROUP BY production_day, fai_name
),
ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY production_day ORDER BY ng_count DESC) AS rank
    FROM fai_stats
    WHERE ng_count > 0
)
SELECT production_day, fai_name, ng_count, total,
       ROUND(ng_count * 100.0 / NULLIF(total, 0), 2) AS ng_rate_pct,
       rank
FROM ranked
WHERE rank <= {{ top_n }}
ORDER BY production_day, rank
"""

# ── 每日 TOP N 不良（回归后） ───────────────────────────

DAILY_TOP_DEFECTS_REGRESSION_QUERY = """
WITH ranked_sn AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY SN ORDER BY TRY_CAST("Time" AS TIMESTAMP) DESC) AS rn,
        MIN(TRY_CAST("Time" AS TIMESTAMP)) OVER (PARTITION BY SN) AS first_prod_time
    FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
    WHERE "Time" IS NOT NULL
    {% if extra_where %} AND {{ extra_where }} {% endif %}
),
latest_only AS (
    SELECT * REPLACE(first_prod_time AS "Time") FROM ranked_sn WHERE rn = 1
),
daily_data AS (
    SELECT COLUMNS('.*_result'),
        CAST(TRY_CAST("Time" AS TIMESTAMP) - INTERVAL '{{ cutoff_hour }} hours' AS DATE) AS production_day
    FROM latest_only
),
unpivoted AS (
    UNPIVOT daily_data
    ON * EXCLUDE (production_day)
    INTO NAME fai_result_col VALUE ng_flag
),
fai_stats AS (
    SELECT
        production_day,
        REPLACE(fai_result_col, '_result', '') AS fai_name,
        SUM(ng_flag) AS ng_count,
        COUNT(*) AS total
    FROM unpivoted
    WHERE fai_result_col != 'overall_result'
    GROUP BY production_day, fai_name
),
ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY production_day ORDER BY ng_count DESC) AS rank
    FROM fai_stats
    WHERE ng_count > 0
)
SELECT production_day, fai_name, ng_count, total,
       ROUND(ng_count * 100.0 / NULLIF(total, 0), 2) AS ng_rate_pct,
       rank
FROM ranked
WHERE rank <= {{ top_n }}
ORDER BY production_day, rank
"""

# ── 按 Vendor 良率 ──────────────────────────────────────────

VENDOR_YIELD_QUERY = """
SELECT
    "Vendor",
    COUNT(*) AS total,
    SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) AS ok_count,
    ROUND(SUM(CASE WHEN overall_result = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS yield_pct
FROM read_parquet('{{ parquet_glob }}', union_by_name=true)
GROUP BY "Vendor"
ORDER BY yield_pct ASC
"""
