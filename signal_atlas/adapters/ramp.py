"""Ramp AI Index public page: detect updates and capture headline adoption figure."""
from __future__ import annotations

import re
from datetime import datetime

from ..fetcher import Fetcher
from ..sanitize import clean_text, meta_content, page_title, strip_html
from .base import AdapterResult, ParseError, RawItem

PAGE = "https://ramp.com/data/ai-index"


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
        figures = re.findall(r"([0-9]{1,2}\.[0-9])%[^.]{0,80}?(?:businesses|companies)", text)
        desc = meta_content(page, "description", "og:description") or ""
        excerpt = clean_text(desc, 200)
        if figures:
            excerpt = (excerpt + f" Headline adoption figure on page: {figures[0]}%.").strip()
        return AdapterResult(items=[RawItem(
            url=PAGE, title=page_title(page) or "Ramp AI Index", source_type="adoption_dataset",
            excerpt=excerpt or None, meta={"claim_status": "dataset", "figures": figures[:5],
                                           "page_hash_basis": len(text)})])
