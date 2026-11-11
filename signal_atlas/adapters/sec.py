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


def _first_str(v: object) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    return (v.strip() or None) if isinstance(v, str) else None


def _filing(hit: object, q: str) -> RawItem | None:
    """One EDGAR hit as a RawItem, or None when the hit lacks an accession, file name or CIK."""
    if not isinstance(hit, dict):
        return None
    src = hit.get("_source")
    src = src if isinstance(src, dict) else {}
    hid, ciks = hit.get("_id"), src.get("ciks")
    cik = str(ciks[0]).strip().lstrip("0") if isinstance(ciks, list) and ciks and ciks[0] is not None else ""
    if not isinstance(hid, str) or ":" not in hid or not cik:
        return None
    acc, fname = hid.split(":", 1)
    name = re.sub(r"\s*\(CIK \d+\)\s*", "", _first_str(src.get("display_names")) or "Unknown filer").strip()
    name = re.sub(r"\s{2,}", " ", name) or "Unknown filer"
    form = _first_str(src.get("form")) or _first_str(src.get("root_forms")) or "filing"
    filed = _first_str(src.get("file_date"))
    filed_at = parse_iso(filed) if filed else None
    period = _first_str(src.get("period_ending"))
    return RawItem(
        url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{fname}",
        title=f"{name} — {form} filed {filed or 'date unknown'}",
        source_type="regulatory_filing",
        excerpt=f"EDGAR full-text match for {q}. Issuer disclosure; open the filing for context.",
        published_at=iso(filed_at) if filed_at else None,
        event_date=period,
        meta={"query": q, "form": form, "cik": cik, "claim_status": "primary"},
    )


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
            hits = data.get("hits") if isinstance(data, dict) else None
            hits = hits.get("hits") if isinstance(hits, dict) else None
            if not isinstance(hits, list):
                res.warnings.append(f"{q}: unexpected EDGAR response shape")
                continue
            ok += 1
            for hit in hits[: self.per_query]:
                item = _filing(hit, q)
                if item:
                    res.items.append(item)
        if ok == 0:
            raise ParseError("all EDGAR queries failed: " + "; ".join(res.warnings[:3]))
        return res
