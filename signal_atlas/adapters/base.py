from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from ..fetcher import Fetcher


class ParseError(Exception):
    pass


@dataclass
class RawItem:
    url: str
    title: str
    source_type: str
    excerpt: str | None = None
    published_at: str | None = None
    event_date: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SeriesUpdate:
    id: str
    label: str
    unit: str
    source_url: str
    attribution: str
    method: str
    points: list[tuple[str, float]]


@dataclass
class AdapterResult:
    items: list[RawItem] = field(default_factory=list)
    series: list[SeriesUpdate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Adapter(Protocol):
    id: str
    name: str
    kind: str  # discovery | primary | dataset
    homepage: str
    access_note: str

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult: ...
