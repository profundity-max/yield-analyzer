from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AIM D-T 数据分析"
    environment: str = "development"
    secret_key: str = Field(default="dev-only-change-me", min_length=16)
    database_url: str = "sqlite:///./storage/aim_dt.sqlite3"
    duckdb_path: str = "./storage/aim_dt.duckdb"
    storage_dir: str = "./storage"
    session_idle_minutes: int = 720
    session_max_days: int = 7
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    max_upload_bytes: int = 1024 * 1024 * 1024
    worker_poll_seconds: float = 1.0
    worker_stale_seconds: int = 300
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "ChangeMe123!"
    force_password_change: bool = True
    day_cutoff_hour: int = 8
    timezone: str = "Asia/Shanghai"
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir).expanduser().resolve()

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    (settings.storage_path / "originals").mkdir(exist_ok=True)
    (settings.storage_path / "parquet").mkdir(exist_ok=True)
    (settings.storage_path / "snapshots").mkdir(exist_ok=True)
    return settings
