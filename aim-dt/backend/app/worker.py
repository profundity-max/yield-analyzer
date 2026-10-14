from __future__ import annotations

import logging
import signal
import time

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models import Batch, User  # noqa: F401
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


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    Base.metadata.create_all(engine)
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
