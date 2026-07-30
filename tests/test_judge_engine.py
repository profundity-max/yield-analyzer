"""
judge/engine.py 核心函数单元测试

覆盖 3 个最关键的纯函数:
- _fuzzy_match_column: FAI 列名模糊匹配
- _build_limit_arrays: Spec 限制数组构造
- _judge_values: FAI 测量值向量判定
"""
import math

import numpy as np
import pytest

from src.judge.engine import (
    _fuzzy_match_column,
    _build_limit_arrays,
    _judge_values,
)
from src.config import SPEC_INF_VALUE


# ════════════════════════════════════════════════════════════
# _fuzzy_match_column
# ════════════════════════════════════════════════════════════


class TestFuzzyMatchColumn:
    """FAI 列名模糊匹配: Spec FAI 找不到时, 尝试 _T ↔ _Z 等后缀变换"""

    def test_exact_match_returns_none(self):
        """精确匹配不在此函数职责内 (调用者应先查 data_columns)"""
        assert _fuzzy_match_column("FAI1", {"FAI1"}, set()) is None

    def test_z_to_t_swap(self):
        """Spec 是 _Z, Data 是 _T → 匹配 _T"""
        result = _fuzzy_match_column("FAI14_A01_Z", {"FAI14_A01_T"}, set())
        assert result == "FAI14_A01_T"

    def test_t_to_z_swap(self):
        """Spec 是 _T, Data 是 _Z → 匹配 _Z"""
        result = _fuzzy_match_column("FAI14_A01_T", {"FAI14_A01_Z"}, set())
        assert result == "FAI14_A01_Z"

    def test_lowercase_swap(self):
        """小写 _t / _z 也能互换"""
        result = _fuzzy_match_column("FAI14_A01_z", {"FAI14_A01_t"}, set())
        assert result == "FAI14_A01_t"

    def test_no_match_returns_none(self):
        """没找到对应后缀 → None"""
        result = _fuzzy_match_column("FAI14_A01_X", {"FAI14_A01_Y"}, set())
        assert result is None

    def test_skip_meta_columns(self):
        """如果候选列是元数据列 (小写), 跳过"""
        result = _fuzzy_match_column("FAI14_A01_Z", {"project"}, {"project"})
        assert result is None

    def test_no_suffix_returns_none(self):
        """无后缀的 FAI 不会触发任何 swap"""
        result = _fuzzy_match_column("FAI14", {"FAI15"}, set())
        assert result is None


# ════════════════════════════════════════════════════════════
# _build_limit_arrays
# ════════════════════════════════════════════════════════════


class TestBuildLimitArrays:
    """根据 Spec 构造下限和上限 NumPy 数组"""

    def test_no_spec_returns_inf(self):
        """无 spec 限制 → 双向 ±inf"""
        lower, upper = _build_limit_arrays(["FAI1", "FAI2"], {})
        assert np.array_equal(lower, [-np.inf, -np.inf])
        assert np.array_equal(upper, [np.inf, np.inf])

    def test_normal_spec(self):
        """正常的上下限"""
        lower, upper = _build_limit_arrays(
            ["FAI1", "FAI2"],
            {"FAI1": {"lower": 0, "upper": 10}, "FAI2": {"lower": -5, "upper": 5}},
        )
        assert np.array_equal(lower, [0, -5])
        assert np.array_equal(upper, [10, 5])

    def test_inf_value_treated_as_no_limit(self):
        """SPEC_INF_VALUE 标记值 → 该方向无限制"""
        lower, upper = _build_limit_arrays(
            ["FAI1", "FAI2"],
            {"FAI1": {"lower": SPEC_INF_VALUE, "upper": 100},
             "FAI2": {"lower": 0, "upper": SPEC_INF_VALUE}},
        )
        # FAI1: 下无限制 (-inf), 上有限
        assert lower[0] == -np.inf
        assert upper[0] == 100
        # FAI2: 下有限, 上无限制
        assert lower[1] == 0
        assert upper[1] == np.inf

    def test_negative_inf_treated_as_no_lower(self):
        """-SPEC_INF_VALUE → 无下限"""
        lower, upper = _build_limit_arrays(
            ["FAI1"], {"FAI1": {"lower": -SPEC_INF_VALUE, "upper": 100}}
        )
        assert lower[0] == -np.inf
        assert upper[0] == 100

    def test_none_value_treated_as_no_limit(self):
        """None → 该方向无限制"""
        lower, upper = _build_limit_arrays(
            ["FAI1"], {"FAI1": {"lower": None, "upper": None}}
        )
        assert lower[0] == -np.inf
        assert upper[0] == np.inf

    def test_nan_value_treated_as_no_limit(self):
        """NaN → 该方向无限制"""
        lower, upper = _build_limit_arrays(
            ["FAI1"], {"FAI1": {"lower": float("nan"), "upper": float("nan")}}
        )
        assert math.isinf(lower[0]) and lower[0] < 0
        assert math.isinf(upper[0]) and upper[0] > 0

    def test_partial_spec_only_for_listed_columns(self):
        """spec 只为部分 FAI 定义时, 其它保持 ±inf"""
        lower, upper = _build_limit_arrays(
            ["FAI1", "FAI2", "FAI3"],
            {"FAI2": {"lower": 0, "upper": 10}},
        )
        assert lower[0] == -np.inf  # FAI1
        assert lower[1] == 0         # FAI2
        assert lower[2] == -np.inf  # FAI3


# ════════════════════════════════════════════════════════════
# _judge_values (核心判定逻辑)
# ════════════════════════════════════════════════════════════


class TestJudgeValues:
    """FAI 测量值向量化判定 (整个项目的核心算法)"""

    def test_all_ok(self):
        """所有值都在范围内 → 全部 OK"""
        fai_values = np.array([[1.0, 2.0], [3.0, 4.0]])
        lower = np.array([0.0, 0.0])
        upper = np.array([10.0, 10.0])
        ok_mask, fai_results, overall = _judge_values(fai_values, lower, upper)
        assert np.all(ok_mask)
        assert np.array_equal(fai_results, [[0, 0], [0, 0]])
        assert np.array_equal(overall, [0, 0])

    def test_below_lower_is_ng(self):
        """低于下限 → NG"""
        fai_values = np.array([[-1.0]])  # 低于 lower=0
        lower = np.array([0.0])
        upper = np.array([10.0])
        ok_mask, fai_results, overall = _judge_values(fai_values, lower, upper)
        assert not ok_mask[0, 0]
        assert fai_results[0, 0] == 1
        assert overall[0] == 1

    def test_above_upper_is_ng(self):
        """高于上限 → NG"""
        fai_values = np.array([[15.0]])
        lower = np.array([0.0])
        upper = np.array([10.0])
        ok_mask, fai_results, overall = _judge_values(fai_values, lower, upper)
        assert not ok_mask[0, 0]
        assert fai_results[0, 0] == 1

    def test_boundary_values_are_ok(self):
        """边界值 (lower, upper) 包含, 视为 OK"""
        fai_values = np.array([[0.0, 10.0]])  # 正好在边界
        lower = np.array([0.0, 0.0])
        upper = np.array([10.0, 10.0])
        ok_mask, fai_results, overall = _judge_values(fai_values, lower, upper)
        assert np.all(ok_mask)

    def test_nan_treated_as_ok(self):
        """NaN (#REF! 等不可判定) → 视为 OK (不扣良率)"""
        fai_values = np.array([[float("nan"), 5.0]])
        lower = np.array([0.0, 0.0])
        upper = np.array([10.0, 10.0])
        ok_mask, _, _ = _judge_values(fai_values, lower, upper)
        # NaN 列应被判为 OK
        assert ok_mask[0, 0]
        assert ok_mask[0, 1]

    def test_one_ng_makes_overall_ng(self):
        """只要有一个 FAI NG, 整条 SN 视为 NG"""
        fai_values = np.array([[5.0, 15.0]])  # FAI2 NG
        lower = np.array([0.0, 0.0])
        upper = np.array([10.0, 10.0])
        _, _, overall = _judge_values(fai_values, lower, upper)
        assert overall[0] == 1

    def test_no_lower_infinity_allows_negative(self):
        """下无限制 (-inf) 时, 负数也 OK"""
        fai_values = np.array([[-999.0]])
        lower = np.array([-np.inf])
        upper = np.array([10.0])
        ok_mask, _, _ = _judge_values(fai_values, lower, upper)
        assert ok_mask[0, 0]

    def test_no_upper_infinity_allows_huge(self):
        """上无限制 (+inf) 时, 极大值也 OK"""
        fai_values = np.array([[1e9]])
        lower = np.array([0.0])
        upper = np.array([np.inf])
        ok_mask, _, _ = _judge_values(fai_values, lower, upper)
        assert ok_mask[0, 0]

    def test_batch_of_10k_rows_performance(self):
        """性能 smoke: 10k 行 × 20 FAI 应 < 1 秒"""
        import time
        N, F = 10000, 20
        fai_values = np.random.rand(N, F) * 10
        lower = np.zeros(F)
        upper = np.full(F, 10.0)
        start = time.time()
        ok_mask, fai_results, overall = _judge_values(fai_values, lower, upper)
        elapsed = time.time() - start
        assert elapsed < 1.0, f"10k×20 判定耗时 {elapsed:.2f}s, 超 1s"
        assert ok_mask.shape == (N, F)
        assert overall.shape == (N,)

    def test_int_values_treated_correctly(self):
        """整数测量值也应正确判定"""
        fai_values = np.array([[5, 5], [5, 15], [-1, 5]], dtype=np.int32)
        lower = np.array([0, 0])
        upper = np.array([10, 10])
        _, fai_results, overall = _judge_values(fai_values, lower, upper)
        # 行 0: 都 OK
        assert fai_results[0].tolist() == [0, 0]
        # 行 1: FAI2 NG
        assert fai_results[1].tolist() == [0, 1]
        # 行 2: FAI1 NG
        assert fai_results[2].tolist() == [1, 0]
        # 整体
        assert overall.tolist() == [0, 1, 1]
