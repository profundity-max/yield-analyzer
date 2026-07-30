"""
任务状态数据模型
"""

from datetime import datetime
from typing import Optional
from enum import Enum


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    IMPORT = "import"
    SPEC_LOAD = "spec_load"
    JUDGE = "judge"
    REJUDGE = "rejudge"
    AGGREGATE = "aggregate"
    EXPORT = "export"


class TaskInfo:
    """任务状态信息"""

    def __init__(
        self,
        task_id: str,
        task_type: TaskType,
        total_steps: int = 0,
    ):
        self.task_id = task_id
        self.task_type = task_type
        self.status = TaskStatus.QUEUED
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.total_steps = total_steps
        self.completed_steps = 0
        self.percentage = 0.0
        self.current_step = ""
        self.estimated_remaining_seconds: Optional[int] = None
        self.errors: list[str] = []
        self.result: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value if isinstance(self.task_type, TaskType) else self.task_type,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "percentage": self.percentage,
            "current_step": self.current_step,
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "errors": self.errors,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskInfo":
        info = cls(
            task_id=data["task_id"],
            task_type=TaskType(data["task_type"]),
            total_steps=data.get("total_steps", 0),
        )
        info.status = TaskStatus(data["status"])
        info.started_at = datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
        info.finished_at = datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None
        info.completed_steps = data.get("completed_steps", 0)
        info.percentage = data.get("percentage", 0.0)
        info.current_step = data.get("current_step", "")
        info.estimated_remaining_seconds = data.get("estimated_remaining_seconds")
        info.errors = data.get("errors", [])
        info.result = data.get("result")
        return info
