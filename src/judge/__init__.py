"""
FAI 判定引擎模块

对原始测量数据执行向量化 FAI 判定，支持断点续传和 SN 去重。

主要组件：
  - engine:   核心判定逻辑（NumPy 向量化）
  - chunker:  分块策略 + TaskTracker 进度集成
  - dedup:    SN 回归去重（DuckDB 窗口函数）
  - cli:      Click 命令行入口
"""

from src.judge.engine import judge_batch, get_fai_columns_from_parquet
from src.judge.chunker import process_with_progress
from src.judge.dedup import apply_regression_rules, get_regression_summary

__all__ = [
    "judge_batch",
    "get_fai_columns_from_parquet",
    "process_with_progress",
    "apply_regression_rules",
    "get_regression_summary",
]
