"""Long-running scheduler process: ingests at 08:00 and 16:00 America/New_York, independent of any browser."""
from __future__ import annotations

import logging
import signal
import sys
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings, get_settings
from .db import connect, dumps
from .pipeline import get_status, run_pipeline
from .scheduling import SLOTS
from .seed import seed_if_empty
from .timeutil import NY, iso, utcnow

log = logging.getLogger("signal_atlas.worker")


def ingest_job(settings: Settings, trigger: str = "scheduled") -> dict[str, Any]:
    conn = connect(settings.db_path)
    try:
        result = run_pipeline(conn, settings, trigger)
        log.info("ingest (%s) finished: %s", trigger, result.get("status"))
        return result
    finally:
        conn.close()


def heartbeat(settings: Settings, sched: Any) -> None:
    job = sched.get_job("ingest")
    nxt = job.next_run_time if job else None
    conn = connect(settings.db_path)
    try:
        conn.execute("INSERT INTO heartbeats(name, at, detail) VALUES ('scheduler', ?, ?) ON CONFLICT(name) DO UPDATE "
                     "SET at=excluded.at, detail=excluded.detail",
                     (iso(utcnow()), dumps({"next_run": iso(nxt) if nxt else None, "mode": type(sched).__name__})))
    finally:
        conn.close()


def build_scheduler(settings: Settings, background: bool = False) -> Any:
    sched = (BackgroundScheduler if background else BlockingScheduler)(timezone=NY)
    hours = ",".join(str(s.hour) for s in SLOTS)
    sched.add_job(ingest_job, CronTrigger(hour=hours, minute=0, timezone=NY), args=[settings], id="ingest",
                  misfire_grace_time=3600, coalesce=True, max_instances=1, replace_existing=True)
    sched.add_job(heartbeat, "interval", seconds=60, args=[settings, sched], id="heartbeat",
                  next_run_time=utcnow(), replace_existing=True)
    return sched


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    conn = connect(settings.db_path)
    seed_if_empty(conn)
    status = get_status(conn, settings)
    conn.close()
    sched = build_scheduler(settings)
    if status["stale"]:
        log.info("last successful refresh missed a scheduled slot; running catch-up ingestion now")
        sched.add_job(ingest_job, args=[settings, "catch-up"], id="catch-up", next_run_time=utcnow())

    def _stop(*_: Any) -> None:
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    log.info("scheduler started: ingest at %s America/New_York", ", ".join(s.strftime("%H:%M") for s in SLOTS))
    sched.start()


if __name__ == "__main__":
    main()
