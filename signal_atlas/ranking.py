"""Transparent ordering. Scores are ranking points, never probabilities."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .timeutil import parse_iso

WEIGHTS = {"novelty": 0.20, "evidence": 0.35, "relevance": 0.20, "impact": 0.25}
CLAIM_POINTS = {"primary": 1.25, "corroborated": 1.0, "reported": 0.35}

METHOD: dict[str, Any] = {
    "weights": WEIGHTS,
    "scale": "Each component is 0–5 points. The composite is a weighted sum used only for editorial "
             "prioritization (the order of the feed). It is not a probability, forecast, or recommendation.",
    "components": {
        "novelty": "Recency of first publication: 5 points when new, −0.5 per day, floor 1. Unreviewed discovery "
                   "mentions never affect ranking.",
        "evidence": "Points per supporting item (primary 1.25, corroborated 1.0, reported 0.35; context counts half), "
                    "capped at 4, plus up to +1 for independent source diversity.",
        "relevance": "Analyst judgement of usefulness to enterprise-focused investors and corporate innovation teams.",
        "impact": "Analyst judgement of potential economic magnitude if the signal holds.",
    },
}


def evidence_strength(evidence: list[dict[str, Any]]) -> float:
    pts = 0.0
    for e in evidence:
        base = CLAIM_POINTS.get(e["claim_type"], 0.0)
        if e["stance"] == "supports":
            pts += base
        elif e["stance"] == "context":
            pts += base / 2
    sources = {e.get("source_name") or e.get("canonical_url") for e in evidence}
    diversity = min(1.0, 0.25 * max(0, len(sources) - 1))
    return round(min(5.0, min(4.0, pts) + diversity), 2)


def novelty(first_published: str, now: datetime) -> float:
    fp = parse_iso(first_published) or now
    age_days = max(0.0, (now - fp).total_seconds() / 86400)
    return round(max(1.0, 5.0 - 0.5 * age_days), 2)


def score_signal(sig: dict[str, Any], now: datetime) -> dict[str, float]:
    analyst = sig.get("analyst_scores") or {}
    comps = {
        "novelty": novelty(sig["first_published_at"], now),
        "evidence": evidence_strength(sig.get("evidence", [])),
        "relevance": float(analyst.get("relevance", 3)),
        "impact": float(analyst.get("impact", 3)),
    }
    comps["composite"] = round(sum(WEIGHTS[k] * comps[k] for k in WEIGHTS), 2)
    return comps
