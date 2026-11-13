"""Ramp AI Index public page: detect updates and capture headline adoption figure."""
from __future__ import annotations

import re
from datetime import datetime

from ..fetcher import Fetcher
from ..sanitize import clean_text, meta_content, page_title, strip_html
from .base import AdapterResult, ParseError, RawItem

PAGE = "https://ramp.com/data/ai-index"
_PCT = r"(?P<pct>[0-9]{1,3}(?:\.[0-9]+)?)%"
# The page's metric table ("Metric Oct 2026 Sep 2026 Change AI adoption: All businesses 56.8% ...") and its lead
# sentence ("In October 2026, AI adoption reached 56.8% of U.S. businesses"). Other percentages on the page come
# from article teasers and older releases, so only these two shapes are read.
TABLE_ROW = re.compile(r"Metric\s+(?P<month>[A-Z][a-z]+ [0-9]{4})\s+[A-Z][a-z]+ [0-9]{4}\s+Change\s+"
                       r"AI adoption: All businesses\s+" + _PCT)
LEAD = re.compile(r"In (?P<month>[A-Z][a-z]+ [0-9]{4}),\s+(?:AI adoption reached\s+)?" + _PCT
                  + r" of U\.S\. businesses")


def headline_adoption(text: str) -> tuple[str, str] | None:
    """(month, percent) of all-business AI adoption for the latest month on the page, or None."""
    m = TABLE_ROW.search(text) or LEAD.search(text)
    return (m.group("month"), m.group("pct")) if m else None


class RampAiIndexAdapter:
    id = "ramp_ai_index"
    name = "Ramp AI Index"
    kind = "dataset"
    homepage = PAGE
    access_note = "Public research page; headline figures only, linked to source."

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        page = http.get(PAGE, ttl_s=6 * 3600, accept="text/html").decode("utf-8", "ignore")
        text = strip_html(page)
        if len(text) < 500:
            raise ParseError("Ramp AI Index page returned too little content")
        headline = headline_adoption(text)
        desc = meta_content(page, "description", "og:description") or ""
        excerpt = clean_text(desc, 200)
        meta: dict[str, object] = {"claim_status": "dataset", "figures": [], "page_hash_basis": len(text)}
        res = AdapterResult()
        if headline:
            month, pct = headline
            meta.update(figures=[pct], adoption_month=month)
            if f"{pct}%" not in excerpt:
                excerpt = (excerpt + f" All-business AI adoption, {month}: {pct}%.").strip()
        else:
            res.warnings.append("headline adoption figure not found on page")
        res.items.append(RawItem(url=PAGE, title=page_title(page) or "Ramp AI Index", source_type="adoption_dataset",
                                 excerpt=excerpt or None, meta=meta))
        return res
