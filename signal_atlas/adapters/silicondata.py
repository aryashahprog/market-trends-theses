"""Silicon Data public index page: record each published index value as a dated observation."""
from __future__ import annotations

import re
from datetime import datetime

from ..fetcher import Fetcher
from ..sanitize import strip_html
from ..timeutil import ny_date
from .base import AdapterResult, ParseError, RawItem, SeriesUpdate

PAGE = "https://www.silicondata.com/products/silicon-index"
CODES = {"SDH100RT": "H100 rental", "SDA100RT": "A100 rental", "SDB200RT": "B200 rental",
         "SDB300RT": "B300 rental", "SDH200RT": "H200 rental", "SDLLMTK": "LLM token index"}


class SiliconDataAdapter:
    id = "silicondata"
    name = "Silicon Data index page"
    kind = "dataset"
    homepage = PAGE
    access_note = "Public page values observed at retrieval time (robots allows); no paid data accessed."

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        text = strip_html(http.get(PAGE, ttl_s=3 * 3600, accept="text/html").decode("utf-8", "ignore"))
        found: dict[str, float] = {}
        for code in CODES:
            m = re.search(rf"{code}\b.{{0,120}}?\$\s?([0-9]{{1,3}}\.[0-9]{{2}})", text)
            if m:
                found[code] = float(m.group(1))
        if not found:
            raise ParseError("Silicon Data page layout changed: no index values recognised")
        day = ny_date(now)
        res = AdapterResult()
        for code, value in found.items():
            res.series.append(SeriesUpdate(
                id=f"sd:{code}", label=f"Silicon Data {CODES[code]} ({code})", unit="USD",
                source_url=PAGE, attribution="Source: Silicon Data public index page",
                method="Value displayed on public page, observed by Signal Atlas once per retrieval day",
                points=[(day, value)]))
        summary = "; ".join(f"{CODES[c]} ${v:.2f}" for c, v in found.items())
        res.items.append(RawItem(url=PAGE, title=f"Silicon Data index values observed {day}",
                                 source_type="pricing_dataset", excerpt=summary[:280], event_date=day,
                                 meta={"claim_status": "dataset"}))
        return res
