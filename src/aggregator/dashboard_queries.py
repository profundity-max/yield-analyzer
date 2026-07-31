"""
DashboardQueries — 仪表板查询 facade

把 aggregator 的函数封装成 UI 友好的接口。
页面只 import 这个, 不直接 import aggregator。
- 用 UI 命名 (line, project), 不是内部命名 (cfg)
- 类型更明确 (返回 DataFrame or dict, not raw rows)
- 失败时返回安全的默认值, 不抛异常

原则 (来自 codebase-design):
- "one adapter = hypothetical seam, two = real"
  当前只有 dashboard 一个消费者, 算假设的 seam。
  未来若 CLI/scheduler 也调用, 升级为真实 seam。
- "interface is the test surface"
  UI 测试可以 mock DashboardQueries, 不用碰 DuckDB。
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.aggregator import yield_calc, regression, rectification
from src.aggregator.data_source import get_default_source


class DashboardQueries:
    """
    Dashboard 查询 facade

    Usage:
        dq = DashboardQueries()
        summary = dq.get_summary(line="L1")
        daily = dq.get_daily_yield(line="L1", days=7)
    """

    def get_summary(self, line: Optional[str] = None) -> dict:
        """总体良率汇总 (UI 命名: line, 不是 cfg)"""
        return yield_calc.get_summary(cfg=line) or {
            "total": 0, "ok_count": 0, "ng_count": 0, "yield_pct": 0,
        }

    def get_daily_yield(
        self,
        line: Optional[str] = None,
        days: int = 14,
        cutoff_hour: int = 7,
    ) -> pd.DataFrame:
        """按日良率, 返回 DataFrame (UI 友好)"""
        rows = yield_calc.get_daily_yield(cfg=line, cutoff_hour=cutoff_hour)
        df = pd.DataFrame(rows)
        if df.empty or "production_day" not in df.columns:
            return df
        df["production_day"] = pd.to_datetime(df["production_day"], errors="coerce")
        return df.sort_values("production_day").tail(days).reset_index(drop=True)

    def get_vendor_yield(self) -> pd.DataFrame:
        """按 Vendor 分组良率"""
        rows = yield_calc.get_vendor_yield()
        return pd.DataFrame(rows)

    def get_line_yield(self) -> pd.DataFrame:
        """按 Line 分组良率"""
        rows = yield_calc.get_cfg_yield()
        return pd.DataFrame(rows)

    def get_projects(self) -> list[str]:
        """所有 Project 列表"""
        return yield_calc.list_projects()

    def get_lines_for_project(self, project: str) -> list[str]:
        """某 Project 的 Line 列表"""
        return yield_calc.list_lines_for_project(project)

    def get_daily_yield_by_project_line(
        self,
        project: Optional[str] = None,
        line: Optional[str] = None,
        regression: bool = True,
    ) -> pd.DataFrame:
        """按 Project + Line 分组的每日良率"""
        rows = yield_calc.get_daily_yield_by_project_line(
            project=project, line=line, regression=regression,
        )
        return pd.DataFrame(rows)

    def get_regression_summary(self) -> dict:
        """回归摘要"""
        return regression.get_regression_summary()

    def get_regression_daily(self, line: Optional[str] = None) -> pd.DataFrame:
        """回归后按日良率"""
        rows = regression.get_regression_daily(cfg=line)
        return pd.DataFrame(rows)

    def get_rectification_stats(self) -> dict:
        """整形良率统计"""
        return rectification.get_rectification_stats()

    def get_regression_unique_sn_rawdata(
        self,
        line: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """回归后唯一 SN 原始数据 (UI 命名 line, 内部传 cfg)"""
        return regression.get_regression_unique_sn_rawdata(
            cfg=line, start_date=start_date, end_date=end_date,
        )


# ════════════════════════════════════════════════════════════
# Singleton
# ════════════════════════════════════════════════════════════


_default: Optional[DashboardQueries] = None


def get_default_queries() -> DashboardQueries:
    """获取默认 facade"""
    global _default
    if _default is None:
        _default = DashboardQueries()
    return _default


def set_default_queries(dq: DashboardQueries) -> None:
    """测试时注入 mock"""
    global _default
    _default = dq


__all__ = ["DashboardQueries", "get_default_queries", "set_default_queries"]
