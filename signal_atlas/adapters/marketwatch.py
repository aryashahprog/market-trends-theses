"""MarketWatch headlines via Dow Jones public RSS (the HTML site is access-restricted; not bypassed)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from ..fetcher import Fetcher, FetchError
from ..sanitize import clean_text
from ..timeutil import iso
from .base import AdapterResult, ParseError, RawItem

FEEDS = (
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://feeds.content.dowjones.io/public/rss/mw_bulletins",
)


class MarketWatchAdapter:
    id = "marketwatch"
    name = "MarketWatch (public RSS)"
    kind = "discovery"
    homepage = "https://www.marketwatch.com/"
    access_note = "Headlines and RSS summaries only from public Dow Jones feeds; site pages not scraped."

    def __init__(self, feeds: tuple[str, ...] = FEEDS, lookback_days: int = 3) -> None:
        self.feeds = feeds
        self.lookback_days = lookback_days

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        res = AdapterResult()
        ok = 0
        for feed in self.feeds:
            try:
                root = ET.fromstring(http.get(feed, ttl_s=1800, accept="application/rss+xml"))
            except (FetchError, ET.ParseError) as e:
                res.warnings.append(f"{feed.rsplit('/', 1)[-1]}: {e}")
                continue
            ok += 1
            for item in root.iter("item"):
                link = (item.findtext("link") or "").strip()
                title = clean_text(item.findtext("title"), 200)
                if not link or not title:
                    continue
                pub = None
                try:
                    pd = parsedate_to_datetime(item.findtext("pubDate") or "")
                    pub = pd
                except (TypeError, ValueError):
                    pass
                if pub and pub < now - timedelta(days=self.lookback_days):
                    continue
                res.items.append(RawItem(
                    url=link, title=title, source_type="news_headline",
                    excerpt=clean_text(item.findtext("description"), 220) or None,
                    published_at=iso(pub) if pub else None,
                    meta={"feed": feed, "claim_status": "reported"},
                ))
        if ok == 0:
            raise ParseError("all MarketWatch feeds failed: " + "; ".join(res.warnings))
        return res
