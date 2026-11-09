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


def _obj(v: object) -> dict:
    return v if isinstance(v, dict) else {}


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _summary(idx: dict, skus: list[dict], tok: dict) -> str:
    """Lead excerpt built only from the fields the API actually returned."""
    latest = _obj(idx.get("latest"))
    parts = []
    value = _num(latest.get("value"))
    if value is not None:
        on = f" on {latest['day']}" if isinstance(latest.get("day"), str) else ""
        parts.append(f"Composite {value:.2f}{on} (base 100 = {idx.get('base_day')}).")
    changes = [f"{label} {pct:+.2f}%" for label, pct in
               (("7D", _num(idx.get("change_7d_pct"))), ("30D", _num(idx.get("change_30d_pct")))) if pct is not None]
    if changes:
        parts.append(", ".join(changes) + ".")
    moved = [(g["sku"], pct) for g in skus if (pct := _num(g.get("change_30d_pct"))) is not None]
    if moved:
        top = sorted(moved, key=lambda m: -m[1])[:3]
        parts.append("Top 30D movers: " + ", ".join(f"{sku} {pct:+.1f}% 30D" for sku, pct in top) + ".")
    if tok.get("blended_usd_per_mtok") is not None:
        parts.append(f"Median list token price ${tok['blended_usd_per_mtok']}/M (not usage-weighted).")
    return " ".join(parts)


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
        if not isinstance(idx, dict) or not isinstance(fam, dict):
            raise ParseError("Price of Compute returned an unexpected JSON shape")
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
            if not isinstance(g, dict):
                continue
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
        latest = _obj(idx.get("latest"))
        day = latest.get("day") if isinstance(latest.get("day"), str) else pts[-1][0]
        tok = _obj(fam.get("token"))
        res.items.append(RawItem(
            url=PAGE, title=f"Price of Compute GPU index — {day}", source_type="pricing_dataset",
            excerpt=_summary(idx, skus, tok) or None, published_at=None, event_date=day,
            meta={"claim_status": "dataset", "attribution": ATTRIBUTION}))
        return res
