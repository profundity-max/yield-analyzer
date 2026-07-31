"""
DashboardQueries facade 单元测试

通过 mock aggregator 函数, 测试 facade 的参数翻译是否正确。
"""
import pandas as pd
import pytest

from src.aggregator import dashboard_queries as dq_mod
from src.aggregator.dashboard_queries import DashboardQueries


class TestFacadeSignatures:
    """验证 facade 用 UI 命名, 而不是内部命名"""

    def test_summary_translates_line_to_cfg(self, monkeypatch):
        """get_summary(line=...) 内部应该传 cfg=line"""
        captured = {}

        def fake_get_summary(cfg=None):
            captured["cfg"] = cfg
            return {"total": 100, "ok_count": 90, "ng_count": 10, "yield_pct": 90.0}

        monkeypatch.setattr(dq_mod.yield_calc, "get_summary", fake_get_summary)
        dq = DashboardQueries()
        result = dq.get_summary(line="L1")
        assert captured["cfg"] == "L1"
        assert result["total"] == 100

    def test_summary_returns_safe_default_on_none(self, monkeypatch):
        monkeypatch.setattr(
            dq_mod.yield_calc, "get_summary",
            lambda cfg=None: None,
        )
        dq = DashboardQueries()
        result = dq.get_summary()
        assert result == {"total": 0, "ok_count": 0, "ng_count": 0, "yield_pct": 0}

    def test_daily_yield_returns_dataframe(self, monkeypatch):
        monkeypatch.setattr(
            dq_mod.yield_calc, "get_daily_yield",
            lambda cfg=None, cutoff_hour=7: [
                {"production_day": "2026-07-25", "total": 100, "ok_count": 90,
                 "ng_count": 10, "yield_pct": 90.0},
                {"production_day": "2026-07-26", "total": 110, "ok_count": 100,
                 "ng_count": 10, "yield_pct": 90.9},
            ],
        )
        dq = DashboardQueries()
        df = dq.get_daily_yield(days=7)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "production_day" in df.columns

    def test_daily_yield_respects_days_filter(self, monkeypatch):
        monkeypatch.setattr(
            dq_mod.yield_calc, "get_daily_yield",
            lambda cfg=None, cutoff_hour=7: [
                {"production_day": f"2026-07-{20+i}", "total": 100, "ok_count": 90,
                 "ng_count": 10, "yield_pct": 90.0}
                for i in range(20)
            ],
        )
        dq = DashboardQueries()
        df = dq.get_daily_yield(days=7)
        assert len(df) == 7

    def test_regression_unique_sn_translates_line(self, monkeypatch):
        captured = {}

        def fake_rawdata(cfg=None, start_date=None, end_date=None):
            captured["cfg"] = cfg
            captured["start"] = start_date
            captured["end"] = end_date
            return pd.DataFrame({"SN": ["S1"]})

        monkeypatch.setattr(dq_mod.regression, "get_regression_unique_sn_rawdata", fake_rawdata)
        dq = DashboardQueries()
        df = dq.get_regression_unique_sn_rawdata(
            line="L1", start_date="2026-07-25", end_date="2026-07-30"
        )
        assert captured["cfg"] == "L1"  # line → cfg 翻译
        assert captured["start"] == "2026-07-25"
        assert captured["end"] == "2026-07-30"
        assert len(df) == 1


class TestSingleton:
    def test_default_is_singleton(self):
        dq1 = dq_mod.get_default_queries()
        dq2 = dq_mod.get_default_queries()
        assert dq1 is dq2

    def test_set_replaces(self):
        original = dq_mod.get_default_queries()
        try:
            fake = DashboardQueries()
            dq_mod.set_default_queries(fake)
            assert dq_mod.get_default_queries() is fake
        finally:
            dq_mod.set_default_queries(original)
