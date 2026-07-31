"""
YieldQuery — 良率查询的 deep module

封装"渲染 SQL 模板 → 执行 → 转 dict"这个重复模式。
yield_calc.py 里 5 个浅 wrapper 都变成 1 行调用。

原则 (来自 codebase-design):
- Deletion test 通过: 删掉 get_summary 等浅 wrapper,
  复杂度会集中到 YieldQuery 这一个地方。
- Interface 就是测试面: 写一次 mock YieldQuery 测全部 5 个调用方。
- 调 SQL 模板是 yield_query 的事, yield_calc 只声明 spec。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.db import get_connection
from src.aggregator.data_source import DataSource, get_default_source


# ════════════════════════════════════════════════════════════
# 查询规范
# ════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class QuerySpec:
    """
    良率查询规范

    Attributes:
        template_name: 在 queries.py 中定义的 SQL 模板常量名
        row_mapper: 行 → dict 的映射函数 (把 DuckDB row 转成返回 dict)
        extra_context: 传给 SQL 模板的额外变量 (e.g. cfg_filter, top_n)
    """
    template_name: str
    row_mapper: Callable[[tuple], dict]
    extra_context: dict = field(default_factory=dict)


# ════════════════════════════════════════════════════════════
# Deep Module
# ════════════════════════════════════════════════════════════


class YieldQuery:
    """
    良率查询的 deep module

    知道怎么:
    1. 拿 SQL 模板
    2. 渲染参数 (parquet_glob, cutoff_hour, filters, extra)
    3. 执行 DuckDB
    4. 转换结果为 dict

    调用方只需要声明 QuerySpec, 不用管 SQL 渲染细节。
    """

    def __init__(
        self,
        source: Optional[DataSource] = None,
        conn_factory: Callable = get_connection,
    ):
        """
        Args:
            source: 数据源 (默认全局单例, 测试时可注入 mock)
            conn_factory: DuckDB 连接工厂 (默认全局单例, 测试时可注入 mock)
        """
        self._source = source  # None → 用 get_default_source()
        self._conn_factory = conn_factory

    @property
    def source(self) -> DataSource:
        return self._source or get_default_source()

    def fetch_one(
        self,
        spec: QuerySpec,
        filters=None,
    ) -> Optional[dict]:
        """
        执行单行查询, 返回一个 dict (无结果时 None)

        Usage:
            spec = QuerySpec("SUMMARY_QUERY", _summary_row_mapper)
            result = YieldQuery().fetch_one(spec)
        """
        rows = self._execute(spec, filters)
        if not rows:
            return None
        return spec.row_mapper(rows[0])

    def fetch_all(
        self,
        spec: QuerySpec,
        filters=None,
    ) -> list[dict]:
        """
        执行多行查询, 返回 list[dict]

        Usage:
            spec = QuerySpec("DAILY_YIELD_QUERY", _daily_yield_row_mapper)
            rows = YieldQuery().fetch_all(spec)
        """
        rows = self._execute(spec, filters)
        return [spec.row_mapper(r) for r in rows]

    def _execute(self, spec: QuerySpec, filters) -> list[tuple]:
        """底层: 拿模板 → 渲染 → 执行 → fetchall"""
        from src.aggregator import queries  # 延迟导入避免循环
        template = getattr(queries, spec.template_name)
        sql = self.source.read_sql(
            template,
            filters=filters,
            **spec.extra_context,
        )
        return self._conn_factory().execute(sql).fetchall()


# ════════════════════════════════════════════════════════════
# 默认实例 (singleton)
# ════════════════════════════════════════════════════════════


_default_query: Optional[YieldQuery] = None


def get_default_query() -> YieldQuery:
    """获取默认 YieldQuery 实例"""
    global _default_query
    if _default_query is None:
        _default_query = YieldQuery()
    return _default_query


def set_default_query(q: YieldQuery) -> None:
    """测试时注入 mock query"""
    global _default_query
    _default_query = q


__all__ = ["YieldQuery", "QuerySpec", "get_default_query", "set_default_query"]
