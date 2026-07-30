from __future__ import annotations

"""
分块策略 + 进度管理

包装 judge_batch 调用，集成 TaskTracker 进度跟踪。
负责确定 chunk 总数、创建进度任务、逐 chunk 更新进度和 ETA 估算。

断点续传由 engine.judge_batch 内部处理，本模块仅负责进度展示层。
"""

import logging
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq

from src.config import JUDGE_CHUNK_SIZE
from src.monitor.models import TaskType
from src.monitor.tracker import get_tracker
from src.judge.engine import judge_batch

logger = logging.getLogger(__name__)


def process_with_progress(
    raw_path: str | Path,
    spec_data: dict,
    output_path: str | Path,
    chunk_size: int = JUDGE_CHUNK_SIZE,
    batch_id: Optional[str] = None,
) -> dict:
    """
    带进度跟踪的 FAI 判定处理。

    创建 TaskTracker 任务，在判定过程中持续更新进度百分比、
    当前步骤描述和预估剩余时间。适合 CLI 和 API 调用场景。

    流程：
    1. 从 Parquet 元数据估算总行数和总 chunk 数
    2. 创建 TaskTracker 任务（task_id = "judge_{batch_id}"）
    3. 调用 engine.judge_batch，通过回调逐 chunk 更新进度
    4. 完成后标记任务成功，返回判定摘要

    Args:
        raw_path: 原始 Parquet 文件路径
        spec_data: Spec 数据字典（同 engine.judge_batch）
        output_path: 输出 Parquet 文件路径
        chunk_size: 每 chunk 行数（默认来自 config）
        batch_id: 批次标识，用于 TaskTracker 的 task_id。
                  为 None 时自动从文件名提取。

    Returns:
        dict: 判定摘要（同 engine.judge_batch 返回值）

    Raises:
        FileNotFoundError: raw_path 不存在
        ValueError: Spec 数据无效
    """
    raw_path = Path(raw_path)
    output_path = Path(output_path)

    # ── 自动推断 batch_id ────────────────────────────────────
    if batch_id is None:
        batch_id = raw_path.stem.replace("raw_", "") if raw_path.stem.startswith("raw_") else raw_path.stem

    task_id = f"judge_{batch_id}"

    # ── 估算总 chunk 数（用于进度百分比） ──────────────────
    total_chunks = _estimate_total_chunks(raw_path, chunk_size)

    # ── 创建进度任务 ─────────────────────────────────────────
    tracker = get_tracker()
    tracker.start_task(
        task_id=task_id,
        task_type=TaskType.JUDGE,
        total_steps=total_chunks,
    )

    logger.info("启动判定任务: %s, 预估 %d chunks", task_id, total_chunks)

    # ── 进度回调（桥接 engine → tracker） ────────────────────
    def _on_chunk_progress(completed: int, total: int, description: str):
        """engine 每完成一个 chunk 时调用"""
        tracker.update_progress(
            task_id=task_id,
            completed=completed,
            step_desc=description,
        )

    # ── 执行判定 ─────────────────────────────────────────────
    try:
        result = judge_batch(
            raw_parquet_path=raw_path,
            spec_data=spec_data,
            output_path=output_path,
            chunk_size=chunk_size,
            progress_callback=_on_chunk_progress,
            resume=True,
        )

        # 标记任务完成
        tracker.complete_task(task_id, success=True, result=result)

        logger.info(
            "判定任务完成: %s, 良率 %.2f%%, %d 行",
            task_id, result["yield_rate"], result["total_rows"],
        )

        return result

    except Exception as exc:
        logger.exception("判定任务失败: %s", task_id)
        tracker.fail_task(task_id, str(exc))
        raise


def _estimate_total_chunks(raw_path: Path, chunk_size: int) -> int:
    """
    从 Parquet 元数据估算总 chunk 数。

    从 Parquet 文件元数据读取总行数，除以 chunk_size 并向上取整。
    只读元数据，不加载数据，性能开销极小。

    Args:
        raw_path: Parquet 文件路径
        chunk_size: 每 chunk 行数

    Returns:
        预估的 chunk 总数（至少为 1）
    """
    if not raw_path.exists():
        return 0

    pf = pq.ParquetFile(raw_path)
    total_rows = pf.metadata.num_rows
    pf.close()

    return max(1, (total_rows + chunk_size - 1) // chunk_size)
