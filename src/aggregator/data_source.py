"""
数据源 (DataSource) — 读数据的唯一 seam

领域抽象: judged Parquet 数据
目的: 把数据读出来的位置集中到一个地方, 未来要换 S3 / Delta / 内存库只改这一个文件。

原则 (来自 codebase-design):
- "一个 adapter = 假设的 seam, 两个 = 真实的 seam"
  当前只有 ParquetSource 一个实现, 算假设的 seam。
  但接缝已就位, 未来加 S3Source 验证后再升级为真实 seam。
- "interface is the test surface"
  Tests can swap in MemorySource without touching SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from jinja2 import Template

from src.config import JUDGED_DIR
from src.aggregator.schema import YieldSchema


# ════════════════════════════════════════════════════════════
# 筛选条件
# ════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Filters:
    """
    数据源筛选条件

    Attributes:
        project: Project 过滤 (None=全部)
        line: Line 过滤 (None=全部)
        cutoff_hour: 日切点小时
    """
    project: Optional[str] = None
    line: Optional[str] = None
    cutoff_hour: int = 7

    def where_clause(self) -> str:
        """生成 SQL WHERE 片段, 拼到 read_parquet 之后"""
        parts = []
        if self.project:
            safe = self.project.replace("'", "''")
            parts.append(f'"{YieldSchema.PROJECT}" = \'{safe}\'')
        if self.line:
            safe = self.line.replace("'", "''")
            parts.append(f'"{YieldSchema.LINE}" = \'{safe}\'')
        return " AND ".join(parts)

    def and_sql(self) -> str:
        """生成 ' AND x AND y' 片段 (用于追加到现有 WHERE 后面)"""
        clause = self.where_clause()
        return f" AND {clause}" if clause else ""


# ════════════════════════════════════════════════════════════
# DataSource 接口
# ════════════════════════════════════════════════════════════


from abc import ABC, abstractmethod

class DataSource(ABC):
    """
    数据源抽象 (abstract seam)

    任何「数据从哪来」的问题都通过 DataSource 解答。
    调用方不需要知道是 Parquet, S3, 还是 in-memory DataFrame。
    """

    @abstractmethod
    def read_sql(self, template: str, filters: Filters = None, **context) -> str:
        """
        把 Jinja2 SQL 模板渲染成可执行的 SQL, 注入数据源 + 筛选条件。

        Args:
            template: Jinja2 SQL 模板 (含 {{ parquet_glob }}, {{ cutoff_hour }}, {{ extra_where }})
            filters: 筛选条件
            **context: 额外模板变量 (e.g. cfg_filter, top_n)

        Returns:
            渲染后的 SQL 字符串
        """
        raise NotImplementedError

    @abstractmethod
    def parquet_glob(self) -> str:
        """返回数据源的 glob 表达式 (供模板 {{ parquet_glob }} 使用)"""
        raise NotImplementedError


# ════════════════════════════════════════════════════════════
# Parquet 实现 (生产用)
# ════════════════════════════════════════════════════════════


class ParquetSource(DataSource):
    """从本地 judged Parquet 文件读数据 (生产用)"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or JUDGED_DIR

    def parquet_glob(self) -> str:
        return f"'{str(self._path / 'judged_*.parquet')}'"

    def read_sql(self, template: str, filters: Filters = None, **context) -> str:
        # cutoff_hour 优先从 filters 取, 再从 context 覆盖
        if filters is not None:
            context.setdefault("cutoff_hour", filters.cutoff_hour)
        ctx = {
            "parquet_glob": self.parquet_glob().strip("'"),  # 给模板用, 不带引号
            "extra_where": (filters.and_sql() if filters else ""),
            **context,
        }
        return Template(template).render(**ctx)


# ════════════════════════════════════════════════════════════
# 单例 (default source)
# ════════════════════════════════════════════════════════════


_default_source: Optional[DataSource] = None


def get_default_source() -> DataSource:
    """获取默认数据源 (单例)"""
    global _default_source
    if _default_source is None:
        _default_source = ParquetSource()
    return _default_source


def set_default_source(source: DataSource) -> None:
    """测试时注入 mock 数据源"""
    global _default_source
    _default_source = source
