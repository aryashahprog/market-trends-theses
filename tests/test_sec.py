from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from signal_atlas.adapters.base import ParseError
from signal_atlas.adapters.sec import SecEdgarAdapter

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
HIT = {"_id": "0001769628-26-000461:crwv-20261110.htm",
       "_source": {"ciks": ["0001769628"], "display_names": ["CoreWeave, Inc.  (CRWV)  (CIK 0001769628)"],
                   "form": "8-K", "file_date": "2026-11-10", "period_ending": "2026-11-10"}}


class FakeHttp:
    def __init__(self, *payloads: object) -> None:
        self.payloads = list(payloads)

    def get(self, url: str, **_: object) -> bytes:
        return json.dumps(self.payloads.pop(0)).encode()


def _fetch(*payloads: object):  # type: ignore[no-untyped-def]
    queries = tuple((f"q{i}", "8-K") for i in range(len(payloads)))
    return SecEdgarAdapter("Test research@example.com", queries=queries).fetch(FakeHttp(*payloads), NOW)  # type: ignore[arg-type]


def test_hit_becomes_filing_link() -> None:
    [item] = _fetch({"hits": {"hits": [HIT]}}).items
    assert item.url == "https://www.sec.gov/Archives/edgar/data/1769628/000176962826000461/crwv-20261110.htm"
    assert item.title == "CoreWeave, Inc. (CRWV) — 8-K filed 2026-11-10"
    assert item.published_at and item.published_at.startswith("2026-11-10")
    assert item.meta["cik"] == "1769628"


@pytest.mark.parametrize("src", [
    {"ciks": ["123"], "root_forms": [], "file_date": "2026-11-10"},
    {"ciks": ["123"], "display_names": [None], "form": None, "file_date": None},
    {"ciks": ["123"], "display_names": "Acme Corp", "root_forms": ["10-Q"], "file_date": "not a date"},
])
def test_sparse_hits_fall_back_instead_of_crashing(src: dict) -> None:
    [item] = _fetch({"hits": {"hits": [{"_id": "0000000123-26-000001:a.htm", "_source": src}]}}).items
    assert item.url.endswith("/123/000000012326000001/a.htm")
    assert "None" not in item.title


@pytest.mark.parametrize("hit", ["x", {"_id": 5}, {"_id": "no-colon", "_source": {"ciks": ["1"]}},
                                 {"_id": "a:b.htm", "_source": {"ciks": []}},
                                 {"_id": "a:b.htm", "_source": {"ciks": ["000"]}}])
def test_unusable_hits_are_skipped(hit: object) -> None:
    res = _fetch({"hits": {"hits": [hit, HIT]}})
    assert len(res.items) == 1


def test_malformed_response_only_drops_that_query() -> None:
    res = _fetch([], {"hits": None}, {"hits": {"hits": [HIT]}})
    assert len(res.items) == 1
    assert res.warnings == ["q0: unexpected EDGAR response shape", "q1: unexpected EDGAR response shape"]


def test_all_queries_malformed_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        _fetch([], {"hits": {"hits": "nope"}})


def test_contact_email_required() -> None:
    with pytest.raises(ParseError, match="contact email"):
        SecEdgarAdapter("NoContact/1.0").fetch(FakeHttp(), NOW)  # type: ignore[arg-type]
