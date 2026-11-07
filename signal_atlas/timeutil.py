from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from .config import TIMEZONE

NY = ZoneInfo(TIMEZONE)

_FRACTION = re.compile(r"(\.\d{6})\d+")
_BASIC_OFFSET = re.compile(r"([+-]\d{2})(\d{2})$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    v = _BASIC_OFFSET.sub(r"\1:\2", _FRACTION.sub(r"\1", v))
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            try:
                dt = datetime.strptime(v[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def ny_date(dt: datetime) -> str:
    return dt.astimezone(NY).strftime("%Y-%m-%d")
