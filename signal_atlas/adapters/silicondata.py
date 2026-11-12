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
# Some index cards show only the GPU name, without the code in brackets.
LABEL_CODES = {"H100": "SDH100RT", "A100": "SDA100RT", "B200": "SDB200RT", "B300": "SDB300RT", "H200": "SDH200RT"}
# One index card: "<label>(<code>) $<value> <change>% vs 7D"; the code is optional.
CARD = re.compile(r"(?P<label>[\w.\-]+)\s?(?:\((?P<code>SD[A-Z0-9]+)\))?\s+\$\s?(?P<value>[0-9][0-9,]*\.[0-9]+)"
                  r"\s+[-+]?[0-9.]+%\s+vs\s+7D")


def parse_index_values(text: str) -> dict[str, float]:
    """Index values keyed by code, read only from card-shaped text so navigation and FAQ mentions are ignored."""
    found: dict[str, float] = {}
    for m in CARD.finditer(text):
        code = m.group("code") or LABEL_CODES.get(m.group("label"))
        if code in CODES and code not in found:
            found[code] = float(m.group("value").replace(",", ""))
    return found


class SiliconDataAdapter:
    id = "silicondata"
    name = "Silicon Data index page"
    kind = "dataset"
    homepage = PAGE
    access_note = "Public page values observed at retrieval time (robots allows); no paid data accessed."

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        text = strip_html(http.get(PAGE, ttl_s=3 * 3600, accept="text/html").decode("utf-8", "ignore"))
        found = parse_index_values(text)
        if not found:
            raise ParseError("Silicon Data page layout changed: no index values recognised")
        day = ny_date(now)
        res = AdapterResult()
        missing = [c for c in CODES if c not in found]
        if missing:
            res.warnings.append("no value found on page for " + ", ".join(missing))
        for code, value in found.items():
            res.series.append(SeriesUpdate(
                id=f"sd:{code}", label=f"Silicon Data {CODES[code]} ({code})", unit="USD",
                source_url=PAGE, attribution="Source: Silicon Data public index page",
                method="Value displayed on public page, observed by Market Trends → Theses once per retrieval day",
                points=[(day, value)]))
        summary = "; ".join(f"{CODES[c]} ${v:.2f}" for c, v in found.items())
        res.items.append(RawItem(url=PAGE, title=f"Silicon Data index values observed {day}",
                                 source_type="pricing_dataset", excerpt=summary[:280], event_date=day,
                                 meta={"claim_status": "dataset"}))
        return res
