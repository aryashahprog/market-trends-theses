from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger

from signal_atlas.scheduling import is_stale, next_slot, previous_slot
from signal_atlas.timeutil import NY


def u(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_summer_slots_are_edt():
    assert next_slot(u("2026-07-01T11:00:00Z")) == u("2026-07-01T12:00:00Z")  # 08:00 EDT
    assert next_slot(u("2026-07-01T12:00:00Z")) == u("2026-07-01T20:00:00Z")  # 16:00 EDT


def test_winter_slots_are_est():
    assert next_slot(u("2026-12-01T12:30:00Z")) == u("2026-12-01T13:00:00Z")  # 08:00 EST
    assert next_slot(u("2026-12-01T21:00:00Z")) == u("2026-12-02T13:00:00Z")


def test_dst_transitions():
    assert next_slot(u("2026-03-07T21:30:00Z")) == u("2026-03-08T12:00:00Z")  # spring forward
    assert next_slot(u("2026-10-31T20:30:00Z")) == u("2026-11-01T13:00:00Z")  # fall back
    assert previous_slot(u("2026-11-01T12:59:00Z")) == u("2026-10-31T20:00:00Z")


def test_worker_trigger_agrees_with_slots():
    trig = CronTrigger(hour="8,16", minute=0, timezone=NY)
    for start in ("2026-03-07T21:30:00Z", "2026-10-31T20:30:00Z", "2026-11-05T15:00:00Z"):
        now = u(start)
        assert trig.get_next_fire_time(None, now) == next_slot(now)


def test_staleness_uses_missed_slot_with_grace():
    g = timedelta(minutes=90)
    last = u("2026-11-05T13:05:00Z")  # after the 08:00 EST slot
    assert not is_stale(last, u("2026-11-05T22:00:00Z"), g)  # 16:00 slot still within grace
    assert is_stale(last, u("2026-11-05T23:00:00Z"), g)  # 16:00 slot missed
    assert is_stale(None, u("2026-11-05T23:00:00Z"), g)
