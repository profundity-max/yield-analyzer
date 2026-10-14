from __future__ import annotations

import logging
import signal
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.db import SessionLocal
from app.services.jobs import process_once, recover_stale_jobs
from app.services.storage import init_analytics_db

settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("aim-dt-worker")
running = True


def stop(*_args) -> None:
    global running
    running = False


def wait_for_database() -> None:
    last_error: Exception | None = None
    for _attempt in range(120):
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1 FROM users LIMIT 1"))
            return
        except OperationalError as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError("database migrations did not complete") from last_error


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    wait_for_database()
    init_analytics_db()
    with SessionLocal() as db:
        recover_stale_jobs(db)
    logger.info("worker started")
    while running:
        with SessionLocal() as db:
            try:
                did_work = process_once(db)
            except Exception:
                logger.exception("job failed")
                did_work = True
        if not did_work:
            time.sleep(settings.worker_poll_seconds)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
