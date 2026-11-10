"""Milk Road discovery: public sitemap + per-page title/description (no article bodies)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from ..fetcher import Fetcher, FetchError
from ..sanitize import clean_text, meta_content, page_title
from ..timeutil import iso, parse_iso
from .base import AdapterResult, ParseError, RawItem

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
MAX_PAGE_FAILURES = 2
SECTIONS = {"/podcast/": "podcast", "/ideas/": "newsletter_analysis", "/news/": "news_brief"}


def _slug_title(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-[A-Za-z0-9_-]{11}$", "", slug) if "/podcast/" in url else slug
    return slug.replace("-", " ").strip().capitalize()


class MilkRoadAdapter:
    id = "milkroad"
    name = "Milk Road"
    kind = "discovery"
    homepage = "https://milkroad.com/"
    access_note = "Public sitemap and page metadata only; robots.txt honoured; no article text stored."
    sitemap = "https://milkroad.com/sitemap.xml"

    def __init__(self, lookback_days: int = 7, max_pages: int = 15) -> None:
        self.lookback_days = lookback_days
        self.max_pages = max_pages

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        res = AdapterResult()
        try:
            root = ET.fromstring(http.get(self.sitemap, ttl_s=3 * 3600, accept="application/xml"))
        except ET.ParseError as e:
            raise ParseError("Milk Road sitemap is not valid XML") from e
        cutoff = now - timedelta(days=self.lookback_days)
        entries: list[tuple[datetime, str, str]] = []
        for u in root.findall("sm:url", NS):
            loc = (u.findtext("sm:loc", default="", namespaces=NS) or "").strip()
            lastmod = parse_iso(u.findtext("sm:lastmod", default="", namespaces=NS))
            section = next((v for k, v in SECTIONS.items() if k in loc), None)
            if not loc.startswith("https://milkroad.com/") or not section or not lastmod:
                continue
            if lastmod >= cutoff:
                entries.append((lastmod, loc, section))
        if not entries and not root.findall("sm:url", NS):
            raise ParseError("Milk Road sitemap contained no URLs")
        entries.sort(reverse=True)
        failures = skipped = 0
        for lastmod, loc, section in entries[: self.max_pages]:
            title, desc, published = _slug_title(loc), None, iso(lastmod)
            if failures >= MAX_PAGE_FAILURES:
                skipped += 1
            else:
                try:
                    page = http.get(loc, ttl_s=24 * 3600, accept="text/html").decode("utf-8", "ignore")
                    title = page_title(page) or title
                    title = re.sub(r"\s*[|\-–]\s*Milk Road\s*$", "", title)
                    desc = meta_content(page, "description", "og:description")
                    pub = meta_content(page, "article:published_time")
                    if pub and parse_iso(pub):
                        published = iso(parse_iso(pub))  # type: ignore[arg-type]
                    failures = 0
                except FetchError as e:
                    failures += 1
                    res.warnings.append(f"page metadata unavailable: {e}")
            res.items.append(RawItem(
                url=loc, title=clean_text(title, 200), source_type=section,
                excerpt=clean_text(desc, 280) or None, published_at=published,
                meta={"sitemap_lastmod": iso(lastmod), "claim_status": "reported"},
            ))
        if skipped:
            res.warnings.append(f"skipped page metadata for {skipped} pages after {MAX_PAGE_FAILURES} consecutive "
                                "failures; sitemap titles used")
        return res
