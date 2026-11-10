from __future__ import annotations

from datetime import datetime, timezone

from signal_atlas.adapters.milkroad import MAX_PAGE_FAILURES, MilkRoadAdapter
from signal_atlas.fetcher import FetchError

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _sitemap(n: int) -> bytes:
    urls = "".join(
        f"<url><loc>https://milkroad.com/ideas/story-{i}/</loc><lastmod>2026-11-0{9 - i % 3}T10:00:00Z</lastmod></url>"
        for i in range(n))
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'.encode()


class FakeHttp:
    def __init__(self, n: int, fail: set[int]) -> None:
        self.sitemap, self.fail, self.page_calls = _sitemap(n), fail, 0

    def get(self, url: str, **_: object) -> bytes:
        if url.endswith("sitemap.xml"):
            return self.sitemap
        self.page_calls += 1
        if self.page_calls in self.fail:
            raise FetchError("network error for milkroad.com: ReadTimeout")
        return b"<title>Real headline | Milk Road</title><meta name='description' content='Desc'>"


def test_pages_fetched_when_healthy() -> None:
    http = FakeHttp(4, fail=set())
    res = MilkRoadAdapter().fetch(http, NOW)  # type: ignore[arg-type]
    assert http.page_calls == 4
    assert [i.title for i in res.items] == ["Real headline"] * 4
    assert res.warnings == []


def test_stops_fetching_pages_after_consecutive_failures() -> None:
    http = FakeHttp(6, fail=set(range(1, 100)))
    res = MilkRoadAdapter().fetch(http, NOW)  # type: ignore[arg-type]
    assert http.page_calls == MAX_PAGE_FAILURES
    assert len(res.items) == 6
    assert all(i.title.startswith("Story ") for i in res.items)
    assert res.warnings[-1].startswith(f"skipped page metadata for {6 - MAX_PAGE_FAILURES} pages")


def test_isolated_failure_does_not_trip_breaker() -> None:
    http = FakeHttp(5, fail={1, 3})
    res = MilkRoadAdapter().fetch(http, NOW)  # type: ignore[arg-type]
    assert http.page_calls == 5
    assert len(res.items) == 5
    assert not any(w.startswith("skipped") for w in res.warnings)
