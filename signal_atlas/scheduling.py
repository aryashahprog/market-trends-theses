"""Twice-daily refresh slots in America/New_York (DST-aware via zoneinfo)."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from .timeutil import NY

SLOTS: tuple[time, ...] = (time(8, 0), time(16, 0))


def _slots_around(at: datetime) -> list[datetime]:
    local_day = at.astimezone(NY).date()
    out = []
    for offset in (-2, -1, 0, 1, 2):
        d = local_day + timedelta(days=offset)
        for s in SLOTS:
            out.append(datetime.combine(d, s, tzinfo=NY).astimezone(timezone.utc))
    return sorted(out)


def next_slot(after: datetime) -> datetime:
    return next(s for s in _slots_around(after) if s > after)


def previous_slot(at: datetime) -> datetime:
    return [s for s in _slots_around(at) if s <= at][-1]


def is_stale(last_success: datetime | None, now: datetime, grace: timedelta) -> bool:
    """Stale when the most recent slot whose grace period has elapsed has no success after it."""
    if last_success is None:
        return True
    return last_success < previous_slot(now - grace)
