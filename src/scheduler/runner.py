"""
调度器启动器 — 在 Dashboard 启动时自动运行
"""

import logging

from src.scheduler.jobs import start_scheduler, add_daily_import_job

logger = logging.getLogger(__name__)


def init_default_jobs():
    """初始化默认定时任务"""
    # 占位：后续可从配置文件读取
    logger.info("初始化默认定时任务")

    def _placeholder_scan():
        logger.info("[定时] 扫描新数据目录...")

    add_daily_import_job(_placeholder_scan, hour=8, minute=0)
    start_scheduler()
