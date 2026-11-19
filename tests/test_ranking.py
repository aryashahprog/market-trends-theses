from datetime import datetime, timedelta, timezone

from signal_atlas.ranking import evidence_strength, novelty, publisher, score_signal

NOW = datetime(2026, 11, 19, 14, 0, tzinfo=timezone.utc)
EDGAR = "SEC EDGAR full-text search"


def ev(url, stance="supports", claim="primary", source=EDGAR):
    return {"canonical_url": url, "url": url, "stance": stance, "claim_type": claim, "source_name": source}


def sec(cik, doc="x.htm"):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/000000000026000001/{doc}"


def test_each_sec_filer_is_its_own_publisher():
    assert publisher(ev(sec(1045810))) == publisher(ev(sec("0001045810", "y.htm"))) == "sec.gov/cik/1045810"
    assert publisher(ev(sec(723125))) != publisher(ev(sec(1045810)))
    assert publisher(ev("https://www.ramp.com/data/ai-index", source="Ramp AI Index")) == "ramp.com"
    assert publisher({"stance": "supports", "claim_type": "primary", "source_name": "Seed"}) == "Seed"


def test_filings_from_several_issuers_earn_diversity_through_one_adapter():
    one_issuer = [ev(sec(1045810, f"{i}.htm")) for i in range(2)]
    two_issuers = [ev(sec(1045810)), ev(sec(723125))]
    assert evidence_strength(one_issuer) == 2.5
    assert evidence_strength(two_issuers) == 2.75


def test_counterevidence_neither_adds_points_nor_diversity():
    base = [ev(sec(1045810))]
    with_challenge = base + [ev(sec(723125), stance="challenges")]
    assert evidence_strength(with_challenge) == evidence_strength(base) == 1.25


def test_points_cap_at_four_and_diversity_at_one():
    many = [ev(sec(cik)) for cik in range(1, 10)]
    assert evidence_strength(many) == 5.0
    assert evidence_strength([ev(sec(1), claim="reported"), ev(sec(1), stance="context")]) == 0.97


def test_novelty_decays_half_a_point_a_day_to_a_floor_of_one():
    assert novelty((NOW - timedelta(days=2)).isoformat(), NOW) == 4.0
    assert novelty((NOW - timedelta(days=30)).isoformat(), NOW) == 1.0
    assert novelty((NOW + timedelta(days=1)).isoformat(), NOW) == 5.0


def test_composite_is_the_weighted_sum():
    sig = {"first_published_at": NOW.isoformat(), "evidence": [ev(sec(1045810))],
           "analyst_scores": {"relevance": 4, "impact": 2}}
    s = score_signal(sig, NOW)
    assert s == {"novelty": 5.0, "evidence": 1.25, "relevance": 4.0, "impact": 2.0,
                 "composite": round(0.2 * 5 + 0.35 * 1.25 + 0.2 * 4 + 0.25 * 2, 2)}
