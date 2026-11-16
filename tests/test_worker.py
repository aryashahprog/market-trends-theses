import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fakes import settings_for

from signal_atlas import worker
from signal_atlas.db import connect
from signal_atlas.pipeline import get_status
from signal_atlas.scheduling import next_slot
from signal_atlas.timeutil import NY, iso, utcnow


def u(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[object, dict]] = []
        self.started = False

    def add_job(self, func, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.jobs.append((func, kwargs))

    def start(self) -> None:
        self.started = True


def test_ingest_job_fires_at_every_slot_across_dst(tmp_path):
    sched = worker.build_scheduler(settings_for(tmp_path), background=True)
    job = sched.get_job("ingest")
    assert job.func is worker.ingest_job and job.max_instances == 1 and job.coalesce
    for start in ("2026-03-07T21:30:00Z", "2026-07-01T12:00:00Z", "2026-10-31T20:30:00Z", "2026-11-05T15:00:00Z"):
        now, prev = u(start), None
        for _ in range(4):  # consecutive fire times, not just the first
            fire = job.trigger.get_next_fire_time(prev, now)
            assert fire == next_slot(now - timedelta(microseconds=1)) and fire.astimezone(NY).minute == 0
            prev, now = fire, fire + timedelta(seconds=1)
    assert sched.get_job("heartbeat") is not None


def test_heartbeat_upserts_one_row_that_status_reads_as_alive(tmp_path):
    s = settings_for(tmp_path)
    nxt = datetime(2026, 11, 16, 16, 0, tzinfo=NY)
    sched = SimpleNamespace(get_job=lambda _id: SimpleNamespace(next_run_time=nxt))
    worker.heartbeat(s, sched)
    worker.heartbeat(s, sched)
    conn = connect(s.db_path)
    assert conn.execute("SELECT COUNT(*) FROM heartbeats").fetchone()[0] == 1
    st = get_status(conn, s)["scheduler"]
    assert st["alive"] is True
    assert st["detail"] == {"next_run": "2026-11-16T21:00:00Z", "mode": "SimpleNamespace"}
    assert get_status(conn, s, now=utcnow() + timedelta(minutes=6))["scheduler"]["alive"] is False


def test_heartbeat_without_an_ingest_job_records_no_next_run(tmp_path):
    s = settings_for(tmp_path)
    worker.heartbeat(s, SimpleNamespace(get_job=lambda _id: None))
    assert get_status(connect(s.db_path), s)["scheduler"]["detail"]["next_run"] is None


@pytest.mark.parametrize("fails", [False, True])
def test_ingest_job_closes_its_connection(tmp_path, monkeypatch, fails):
    seen: list[tuple[sqlite3.Connection, str]] = []

    def fake_run(conn, settings, trigger):  # type: ignore[no-untyped-def]
        seen.append((conn, trigger))
        if fails:
            raise RuntimeError("boom")
        return {"status": "success"}

    monkeypatch.setattr(worker, "run_pipeline", fake_run)
    if fails:
        with pytest.raises(RuntimeError):
            worker.ingest_job(settings_for(tmp_path), "catch-up")
    else:
        assert worker.ingest_job(settings_for(tmp_path), "catch-up") == {"status": "success"}
    conn, trigger = seen[0]
    assert trigger == "catch-up"
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def _run_main(tmp_path, monkeypatch) -> FakeScheduler:  # type: ignore[no-untyped-def]
    fake = FakeScheduler()
    monkeypatch.setattr(worker, "get_settings", lambda: settings_for(tmp_path))
    monkeypatch.setattr(worker, "build_scheduler", lambda settings: fake)
    monkeypatch.setattr(worker.signal, "signal", lambda *a: None)
    worker.main()
    assert fake.started
    return fake


def test_main_seeds_and_runs_catch_up_when_the_last_slot_was_missed(tmp_path, monkeypatch):
    fake = _run_main(tmp_path, monkeypatch)
    assert connect(settings_for(tmp_path).db_path).execute("SELECT COUNT(*) FROM signals").fetchone()[0] > 0
    [(func, kw)] = fake.jobs
    assert func is worker.ingest_job and kw["id"] == "catch-up" and kw["args"][1] == "catch-up"


def test_main_skips_catch_up_after_a_recent_success(tmp_path, monkeypatch):
    conn = connect(settings_for(tmp_path).db_path)
    now = iso(utcnow())
    conn.execute("INSERT INTO pipeline_runs(trigger, started_at, finished_at, status) VALUES ('scheduled',?,?,'success')",
                 (now, now))
    assert _run_main(tmp_path, monkeypatch).jobs == []
