"""
任务进度跟踪器

通过文件系统中的 JSON 文件记录和读取任务进度。
进程独立，Dashboard 重启不丢失进度。
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import PROGRESS_DIR
from src.monitor.models import TaskInfo, TaskStatus, TaskType


class TaskTracker:
    """文件系统进度跟踪器"""

    def __init__(self, progress_dir: Path = PROGRESS_DIR):
        self.progress_dir = progress_dir
        self.progress_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, task_id: str) -> Path:
        return self.progress_dir / f"{task_id}.json"

    def start_task(
        self,
        task_id: str,
        task_type: TaskType,
        total_steps: int = 0,
    ) -> TaskInfo:
        """创建并开始一个任务"""
        info = TaskInfo(task_id=task_id, task_type=task_type, total_steps=total_steps)
        info.status = TaskStatus.RUNNING
        info.started_at = datetime.now()
        info.current_step = "初始化..."
        self._save(info)
        return info

    def update_progress(
        self,
        task_id: str,
        completed: int,
        step_desc: str = "",
    ):
        """更新任务进度"""
        info = self._load(task_id)
        if info is None:
            return

        info.completed_steps = completed
        info.current_step = step_desc

        if info.total_steps > 0:
            info.percentage = round(completed / info.total_steps * 100, 1)

            # 估算剩余时间
            if info.started_at and completed > 0:
                elapsed = (datetime.now() - info.started_at).total_seconds()
                rate = elapsed / completed
                remaining = rate * (info.total_steps - completed)
                info.estimated_remaining_seconds = int(remaining)

        self._save(info)

    def complete_task(self, task_id: str, success: bool = True, result: dict = None):
        """标记任务完成"""
        info = self._load(task_id)
        if info is None:
            return

        info.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        info.finished_at = datetime.now()
        info.percentage = 100.0
        info.current_step = "完成" if success else "失败"
        info.estimated_remaining_seconds = 0
        if result:
            info.result = result
        self._save(info)

    def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        info = self._load(task_id)
        if info is None:
            return

        info.status = TaskStatus.FAILED
        info.finished_at = datetime.now()
        info.errors.append(error)
        info.current_step = f"失败: {error}"
        self._save(info)

    def get_status(self, task_id: str) -> Optional[TaskInfo]:
        """读取任务状态"""
        return self._load(task_id)

    def list_tasks(self) -> list[TaskInfo]:
        """列出所有任务"""
        tasks = []
        for f in sorted(self.progress_dir.glob("*.json")):
            try:
                info = self._load_from_file(f)
                if info:
                    tasks.append(info)
            except Exception:
                continue
        return tasks

    def list_running_tasks(self) -> list[TaskInfo]:
        """列出运行中的任务"""
        return [t for t in self.list_tasks() if t.status == TaskStatus.RUNNING]

    # ── 内部方法 ─────────────────────────────

    def _save(self, info: TaskInfo):
        """保存任务状态到文件"""
        with open(self._file_path(info.task_id), "w", encoding="utf-8") as f:
            json.dump(info.to_dict(), f, ensure_ascii=False, indent=2)

    def _load(self, task_id: str) -> Optional[TaskInfo]:
        """从文件加载任务状态"""
        path = self._file_path(task_id)
        if not path.exists():
            return None
        return self._load_from_file(path)

    def _load_from_file(self, path: Path) -> Optional[TaskInfo]:
        """从文件加载"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TaskInfo.from_dict(data)
        except Exception:
            return None


# 全局单例
_tracker: Optional[TaskTracker] = None


def get_tracker() -> TaskTracker:
    """获取全局 TaskTracker 实例"""
    global _tracker
    if _tracker is None:
        _tracker = TaskTracker()
    return _tracker
