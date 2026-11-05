from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx

from signal_atlas.adapters.base import AdapterResult, RawItem, SeriesUpdate
from signal_atlas.config import Settings
from signal_atlas.fetcher import Fetcher, FetchError


def settings_for(tmp: Path, token: str | None = "t" * 32) -> Settings:
    return Settings(db_path=tmp / "test.db", admin_token=token, http_user_agent="SignalAtlasTest/1.0",
                    sec_user_agent="", manual_refresh_min_interval_s=600, stale_grace_minutes=90,
                    run_scheduler_in_web=False)


def null_fetcher(conn) -> Fetcher:  # type: ignore[no-untyped-def]
    return Fetcher(conn, "t", transport=httpx.MockTransport(lambda r: httpx.Response(200)), sleep=lambda s: None)


class Good:
    id, name, kind, homepage, access_note = "good", "Good source", "discovery", "https://good.example", "test"

    def __init__(self, title: str = "Nvidia GPU rental prices climb as inference demand grows",
                 broken_series: bool = False) -> None:
        self.title, self.broken_series = title, broken_series

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        pts: list[tuple[str, float]] = [("2026-11-04", 140.0), ("2026-11-05", 142.3)]
        if self.broken_series:
            pts.append((None, 1.0))  # type: ignore[arg-type]  # violates NOT NULL -> whole source tx rolls back
        return AdapterResult(
            items=[RawItem(url="https://good.example/a?utm_source=x", title=self.title, source_type="news_brief",
                           excerpt="<b>GPU</b> rental and <script>alert(1)</script>token prices", published_at="2026-11-05")],
            series=[SeriesUpdate(id="test:idx", label="Test index", unit="index", source_url="https://good.example",
                                 attribution="Test", method="test", points=pts)])


class Boom:
    id, name, kind, homepage, access_note = "boom", "Failing source", "primary", "https://boom.example", "test"

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        raise FetchError("HTTP 403 (access restricted) for boom.example; not bypassed")
