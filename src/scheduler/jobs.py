"""
定时任务定义

管理自动导入、重算等定时任务。
"""

import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None


def get_scheduler() -> BackgroundScheduler:
    """获取全局调度器实例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def start_scheduler():
    """启动调度器"""
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("调度器已启动")


def stop_scheduler():
    """停止调度器"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("调度器已停止")


def add_daily_import_job(callback, hour: int = 8, minute: int = 0):
    """
    添加每日数据导入任务

    Args:
        callback: 导入回调函数
        hour: 执行时间（时）
        minute: 执行时间（分）
    """
    sched = get_scheduler()
    sched.add_job(
        callback,
        CronTrigger(hour=hour, minute=minute),
        id="daily_import",
        name="每日数据扫描导入",
        replace_existing=True,
    )
    logger.info(f"已添加每日导入任务: {hour:02d}:{minute:02d}")


def add_weekly_validation_job(callback, day_of_week: str = "sun", hour: int = 2):
    """
    添加每周数据校验任务

    Args:
        callback: 校验回调函数
        day_of_week: 周几执行
        hour: 执行时间（时）
    """
    sched = get_scheduler()
    sched.add_job(
        callback,
        CronTrigger(day_of_week=day_of_week, hour=hour),
        id="weekly_validation",
        name="每周数据完整性校验",
        replace_existing=True,
    )
    logger.info(f"已添加每周校验任务: {day_of_week} {hour:02d}:00")


def list_scheduled_jobs() -> list[dict]:
    """列出所有已注册的定时任务"""
    sched = get_scheduler()
    jobs = []
    for job in sched.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return jobs
