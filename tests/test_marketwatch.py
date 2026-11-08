from datetime import datetime, timezone

import pytest

from signal_atlas.adapters.base import ParseError
from signal_atlas.adapters.marketwatch import MarketWatchAdapter
from signal_atlas.fetcher import FetchError

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def _item(title: str, link: str, pub: str = "") -> str:
    return f"<item><title>{title}</title><link>{link}</link><pubDate>{pub}</pubDate></item>"


class FeedHttp:
    def __init__(self, *items: str) -> None:
        self.body = f"<rss><channel>{''.join(items)}</channel></rss>".encode()

    def get(self, url: str, **_: object) -> bytes:
        return self.body


def fetch(*items: str):  # type: ignore[no-untyped-def]
    return MarketWatchAdapter(feeds=("https://example.test/mw",)).fetch(FeedHttp(*items), NOW)  # type: ignore[arg-type]


def test_unknown_timezone_pubdate_is_treated_as_utc_instead_of_crashing():
    res = fetch(_item("Chip stocks rally", "https://www.marketwatch.com/story/a", "Fri, 06 Nov 2026 10:00:00 -0000"))
    assert [i.published_at for i in res.items] == ["2026-11-06T10:00:00Z"]


def test_offset_pubdate_normalised_and_old_items_dropped():
    res = fetch(
        _item("Fresh", "https://www.marketwatch.com/story/b", "Fri, 06 Nov 2026 05:00:00 -0500"),
        _item("Stale", "https://www.marketwatch.com/story/c", "Sun, 01 Nov 2026 10:00:00 GMT"),
        _item("Undated", "https://www.marketwatch.com/story/d", "sometime"),
    )
    assert [(i.title, i.published_at) for i in res.items] == [("Fresh", "2026-11-06T10:00:00Z"), ("Undated", None)]


def test_items_without_title_or_absolute_link_are_skipped():
    res = fetch(
        _item("Relative link", "/story/e"),
        _item("No link", ""),
        _item("", "https://www.marketwatch.com/story/f"),
        _item("Kept", "https://www.marketwatch.com/story/g"),
    )
    assert [i.url for i in res.items] == ["https://www.marketwatch.com/story/g"]


def test_all_feeds_failing_raises_parse_error():
    class Down:
        def get(self, url: str, **_: object) -> bytes:
            raise FetchError("503")

    with pytest.raises(ParseError):
        MarketWatchAdapter(feeds=("https://example.test/a",)).fetch(Down(), NOW)  # type: ignore[arg-type]
