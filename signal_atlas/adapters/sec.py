"""SEC EDGAR full-text search for thesis-relevant disclosures (metadata + links only)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from ..fetcher import Fetcher, FetchError
from ..timeutil import iso, parse_iso
from .base import AdapterResult, ParseError, RawItem

QUERIES: tuple[tuple[str, str], ...] = (
    ('"outcome-based pricing"', "10-Q,10-K,8-K,6-K,20-F,S-1"),
    ('"credits-based pricing"', "10-Q,10-K,8-K,S-1"),
    ('"GPU" "rental"', "10-Q,10-K,8-K,S-1"),
    ('"memory shortage"', "10-Q,10-K,8-K,6-K"),
    ('"private 5G"', "10-Q,10-K,6-K,20-F"),
    ('"AI agents" "per task"', "10-Q,10-K,8-K,S-1"),
    ('"megawatts" "data center"', "10-Q,8-K,S-1"),
)
ENDPOINT = "https://efts.sec.gov/LATEST/search-index"


class SecEdgarAdapter:
    id = "sec_edgar"
    name = "SEC EDGAR full-text search"
    kind = "primary"
    homepage = "https://www.sec.gov/edgar/search/"
    access_note = "Official EDGAR search API; declared User-Agent with contact; well under SEC fair-access limits."

    def __init__(self, user_agent: str, queries: tuple[tuple[str, str], ...] = QUERIES,
                 lookback_days: int = 10, per_query: int = 6) -> None:
        self.user_agent = user_agent
        self.queries = queries
        self.lookback_days = lookback_days
        self.per_query = per_query

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        if not re.search(r"\S+@\S+\.\S+", self.user_agent):
            raise ParseError("SEC_USER_AGENT must include a contact email (SEC fair-access policy)")
        res = AdapterResult()
        ok = 0
        start = (now - timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        for q, forms in self.queries:
            url = ENDPOINT + "?" + urlencode(
                {"q": q, "dateRange": "custom", "startdt": start, "enddt": end, "forms": forms})
            try:
                data = json.loads(http.get(url, ttl_s=6 * 3600, user_agent=self.user_agent,
                                           accept="application/json"))
            except (FetchError, ValueError) as e:
                res.warnings.append(f"{q}: {e}")
                continue
            ok += 1
            for hit in (data.get("hits", {}).get("hits") or [])[: self.per_query]:
                src = hit.get("_source", {})
                try:
                    acc, fname = hit["_id"].split(":", 1)
                    cik = str(src["ciks"][0]).lstrip("0")
                except (KeyError, IndexError, ValueError):
                    continue
                name = re.sub(r"\s*\(CIK \d+\)\s*", "", (src.get("display_names") or ["Unknown filer"])[0]).strip()
                name = re.sub(r"\s{2,}", " ", name)
                form = src.get("form") or src.get("root_forms", ["filing"])[0]
                filed = src.get("file_date")
                period = src.get("period_ending")
                res.items.append(RawItem(
                    url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{fname}",
                    title=f"{name} — {form} filed {filed}",
                    source_type="regulatory_filing",
                    excerpt=f"EDGAR full-text match for {q}. Issuer disclosure; open the filing for context.",
                    published_at=iso(parse_iso(filed)) if parse_iso(filed) else None,  # type: ignore[arg-type]
                    event_date=period,
                    meta={"query": q, "form": form, "cik": cik, "claim_status": "primary"},
                ))
        if ok == 0:
            raise ParseError("all EDGAR queries failed: " + "; ".join(res.warnings[:3]))
        return res
