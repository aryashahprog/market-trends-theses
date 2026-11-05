from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import TIMEZONE

NY = ZoneInfo(TIMEZONE)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        try:
            dt = datetime.strptime(v[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def ny_date(dt: datetime) -> str:
    return dt.astimezone(NY).strftime("%Y-%m-%d")
