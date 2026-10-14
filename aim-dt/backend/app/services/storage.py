from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from pathlib import Path

import duckdb
from fastapi import UploadFile

from app.config import get_settings

settings = get_settings()


def safe_name(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", base)
    return base[:180] or "upload.bin"


def batch_paths(batch_id: str) -> tuple[Path, Path]:
    original_dir = settings.storage_path / "originals" / batch_id
    parquet_dir = settings.storage_path / "parquet"
    original_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    return original_dir, parquet_dir


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def save_upload(upload: UploadFile, batch_id: str) -> tuple[Path, int, str]:
    original_dir, _ = batch_paths(batch_id)
    safe = safe_name(upload.filename or "upload.bin")
    destination = original_dir / safe
    total = 0
    with destination.open("wb") as stream:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_bytes:
                stream.close()
                destination.unlink(missing_ok=True)
                raise ValueError(f"文件超过上限 {settings.max_upload_bytes} bytes")
            stream.write(chunk)
    return destination, total, sha256_file(destination)


def copy_file_to_batch(
    source: Path, batch_id: str, filename: str | None = None
) -> tuple[Path, int, str]:
    original_dir, _ = batch_paths(batch_id)
    destination = original_dir / safe_name(filename or source.name)
    shutil.copy2(source, destination)
    return destination, destination.stat().st_size, sha256_file(destination)


def duckdb_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(Path(settings.duckdb_path).resolve()), read_only=read_only)
    connection.execute("SET threads TO 8")
    connection.execute("SET memory_limit='12GB'")
    return connection


def init_analytics_db() -> None:
    con = duckdb_connection()
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id VARCHAR PRIMARY KEY,
                event_hash VARCHAR NOT NULL,
                sn VARCHAR NOT NULL,
                detected_at TIMESTAMP NOT NULL,
                production_day DATE NOT NULL,
                config VARCHAR,
                site_name VARCHAR,
                equipment_id VARCHAR,
                slot VARCHAR,
                processing_ms DOUBLE,
                original_final_result VARCHAR,
                measurement_json JSON NOT NULL,
                source_sequence BIGINT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_hash ON events(event_hash)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_sn_time ON events(sn, detected_at)")
    finally:
        con.close()


def new_batch_id() -> str:
    return str(uuid.uuid4())
