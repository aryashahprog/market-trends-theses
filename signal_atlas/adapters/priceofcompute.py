"""Price of Compute public API: daily GPU on-demand indices (attribution required)."""
from __future__ import annotations

import json
from datetime import datetime

from ..fetcher import Fetcher
from .base import AdapterResult, ParseError, RawItem, SeriesUpdate

BASE = "https://www.priceofcompute.com/api/v1"
ATTRIBUTION = "Data: Price of Compute — priceofcompute.com"
PAGE = "https://www.priceofcompute.com/indices"


def _points(series: list[dict]) -> list[tuple[str, float]]:
    out = []
    for p in series:
        if isinstance(p, dict) and isinstance(p.get("day"), str) and isinstance(p.get("value"), int | float):
            out.append((p["day"], float(p["value"])))
    return out


class PriceOfComputeAdapter:
    id = "priceofcompute"
    name = "Price of Compute"
    kind = "dataset"
    homepage = PAGE
    access_note = "Free public API (no key, <1,000 req/day); cached; attribution shown with every chart."

    def fetch(self, http: Fetcher, now: datetime) -> AdapterResult:
        res = AdapterResult()
        try:
            idx = json.loads(http.get(f"{BASE}/index", ttl_s=3 * 3600, accept="application/json"))
            fam = json.loads(http.get(f"{BASE}/index-family?series=1", ttl_s=3 * 3600, accept="application/json"))
        except ValueError as e:
            raise ParseError("Price of Compute returned non-JSON") from e
        pts = _points(idx.get("series") or [])
        if not pts:
            raise ParseError("Price of Compute index had no series")
        base_day = idx.get("base_day")
        res.series.append(SeriesUpdate(
            id="poc:composite", label="Price of Compute GPU index (composite)",
            unit=f"index, {base_day} = 100", source_url=PAGE, attribution=ATTRIBUTION,
            method=str(idx.get("note") or "Weighted on-demand basket"), points=pts))
        skus = []
        for g in fam.get("gpu") or []:
            sku = g.get("sku")
            sp = _points(g.get("series") or [])
            if not sku or not sp:
                continue
            skus.append(g)
            res.series.append(SeriesUpdate(
                id=f"poc:sku:{sku}", label=f"{sku} on-demand index", unit=f"index, {g.get('base_day')} = 100",
                source_url=PAGE, attribution=ATTRIBUTION,
                method=f"Daily on-demand median rebased to 100 (base ${g.get('base_price_usd_hr')}/GPU-hr)",
                points=sp))
        latest = idx.get("latest") or {}
        tok = fam.get("token") or {}
        movers = sorted(skus, key=lambda g: -(g.get("change_30d_pct") or 0))[:3]
        mv = ", ".join(f"{g['sku']} {g.get('change_30d_pct'):+.1f}% 30D" for g in movers)
        excerpt = (f"Composite {latest.get('value'):.2f} on {latest.get('day')} (base 100 = {base_day}); "
                   f"7D {idx.get('change_7d_pct'):+.2f}%, 30D {idx.get('change_30d_pct'):+.2f}%. "
                   f"Top 30D movers: {mv}.")
        if tok.get("blended_usd_per_mtok") is not None:
            excerpt += f" Median list token price ${tok['blended_usd_per_mtok']}/M (not usage-weighted)."
        res.items.append(RawItem(
            url=PAGE, title=f"Price of Compute GPU index — {latest.get('day')}", source_type="pricing_dataset",
            excerpt=excerpt, published_at=None, event_date=latest.get("day"),
            meta={"claim_status": "dataset", "attribution": ATTRIBUTION}))
        return res
