"""
Yield Schema — 良率数据 schema 单一来源

所有良率数据的列名、判定结果常量集中在一处。
任何"CFG 在哪里"的问题都通过这里解答。

原则 (来自 codebase-design):
- 单一 source of truth: 一次定义, 全栈引用
- AI 可导航: 任何 AI agent 找列名只需查这里
- Renames touch 1 file: CFG→Line 那种重命名不会再污染 5 个模块

术语 (来自 CONTEXT.md):
- SN, Time, FAI, Project, Vendor, Line 都是良率数据的标准列
- _result 后缀是 judge 引擎生成的判定结果列
- overall_result 是整条 SN 的最终判定
"""

from __future__ import annotations


class YieldSchema:
    """
    良率数据 schema 单一来源

    任何 SQL 模板、Python 代码、UI 引用列名时都从这里取。
    """

    # ── 元数据列 ───────────────────────────────────────
    SN: str = "SN"
    TIME: str = "Time"
    PROJECT: str = "Project"
    VENDOR: str = "Vendor"
    LINE: str = "Line"

    # ── 旧字段 (向后兼容, 见 ADR-0004) ───────────────
    YIELD1_OLD: str = "Yield1"   # → Project
    YIELD2_OLD: str = "Yield2"   # → Vendor
    CFG_OLD: str = "CFG"          # → Line

    # ── FAI 相关 ──────────────────────────────────────
    FAI_PREFIX: str = "FAI"
    RESULT_SUFFIX: str = "_result"
    OVERALL_RESULT: str = "overall_result"

    # ── 派生方法 ──────────────────────────────────────

    @classmethod
    def fai_result_col(cls, fai_base: str) -> str:
        """FAI 判定结果列名, 如 FAI312 → FAI312_result"""
        return f"{fai_base}{cls.RESULT_SUFFIX}"

    @classmethod
    def is_result_col(cls, col: str) -> bool:
        """判断列名是否为 FAI 判定结果列"""
        return col.endswith(cls.RESULT_SUFFIX) and col != cls.OVERALL_RESULT

    @classmethod
    def base_fai_name(cls, result_col: str) -> str:
        """从判定列名反推 FAI 基础名, 如 FAI312_result → FAI312"""
        if not cls.is_result_col(result_col):
            raise ValueError(f"{result_col} is not a result column")
        return result_col[: -len(cls.RESULT_SUFFIX)]


__all__ = ["YieldSchema"]
