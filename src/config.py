"""
全局配置模块

所有模块共享的配置项集中管理，支持环境变量覆盖。
"""

import os
from pathlib import Path

# ── 项目根目录 ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 数据目录 ───────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
JUDGED_DIR = DATA_DIR / "judged"
UPLOADS_DIR = DATA_DIR / "uploads"
PROGRESS_DIR = DATA_DIR / "progress"
EXPORTS_DIR = DATA_DIR / "exports"
ARCHIVE_DIR = DATA_DIR / "archive"
LOGS_DIR = PROJECT_ROOT / "logs"

# 确保所有目录存在
for _dir in [RAW_DIR, JUDGED_DIR, UPLOADS_DIR, PROGRESS_DIR, EXPORTS_DIR, ARCHIVE_DIR, LOGS_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# ── DuckDB 配置 ────────────────────────────────────────
DUCKDB_MEMORY_LIMIT = os.environ.get("YIELD_DB_MEMORY_LIMIT", "6GB")
DUCKDB_THREADS = int(os.environ.get("YIELD_DB_THREADS", "8"))
DUCKDB_TEMP_DIR = os.environ.get("YIELD_DB_TEMP_DIR", str(DATA_DIR))

# ── 判定引擎配置 ───────────────────────────────────────
JUDGE_CHUNK_SIZE = int(os.environ.get("YIELD_JUDGE_CHUNK_SIZE", "25000"))  # 每chunk行数

# ── Excel 导入配置 ─────────────────────────────────────
EXCEL_CHUNK_SIZE = int(os.environ.get("YIELD_EXCEL_CHUNK_SIZE", "50000"))  # Parquet写入chunk

# ── 日切点配置（小时） ─────────────────────────────────
DAY_CUTOFF_HOUR = int(os.environ.get("YIELD_DAY_CUTOFF_HOUR", "7"))  # 默认早上7:00切点

# ── Spec 无穷值 ────────────────────────────────────────
SPEC_INF_VALUE = 999999  # Spec中此值表示无限制


def get_raw_parquet_files() -> list[Path]:
    """获取所有原始 Parquet 文件"""
    return sorted(RAW_DIR.glob("raw_*.parquet"))


def get_judged_parquet_files() -> list[Path]:
    """获取所有已判定 Parquet 文件"""
    return sorted(JUDGED_DIR.glob("judged_*.parquet"))
