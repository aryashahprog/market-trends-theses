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


def _hit(acc: str, fname: str, file_type: str | None = None) -> dict:
    src = dict(HIT["_source"], **({"file_type": file_type} if file_type else {}))
    return {"_id": f"{acc}:{fname}", "_source": src}


def test_exhibits_are_labelled_as_exhibits() -> None:
    [main, ex] = _fetch({"hits": {"hits": [_hit("0001769628-26-000461", "crwv.htm", "8-K"),
                                           _hit("0001769628-26-000462", "ex99.htm", "EX-99.1")]}}).items
    assert main.title == "CoreWeave, Inc. (CRWV) — 8-K filed 2026-11-10" and main.meta["exhibit"] is None
    assert ex.title == "CoreWeave, Inc. (CRWV) — 8-K filed 2026-11-10 (exhibit EX-99.1)"


def test_one_item_per_filing_across_exhibits_and_queries() -> None:
    a, b = "0001769628-26-000461", "0001769628-26-000470"
    res = _fetch({"hits": {"hits": [_hit(a, "ex10-1.htm", "EX-10.1"), _hit(a, "ex10-16.htm", "EX-10.16"),
                                    _hit(b, "main.htm", "10-Q")]}},
                 {"hits": {"hits": [_hit(b, "ex99.htm", "EX-99.1")]}})
    assert [i.url.rsplit("/", 1)[1] for i in res.items] == ["ex10-1.htm", "main.htm"]


def test_per_query_cap_counts_distinct_filings() -> None:
    hits = [_hit("0001769628-26-000461", f"ex{i}.htm", "EX-10.1") for i in range(3)]
    hits += [_hit(f"0001769628-26-00050{i}", "m.htm", "8-K") for i in range(7)]
    queries = (("q0", "8-K"),)
    res = SecEdgarAdapter("Test research@example.com", queries=queries).fetch(  # type: ignore[arg-type]
        FakeHttp({"hits": {"hits": hits}}), NOW)
    assert len(res.items) == 6 and len({i.meta["accession"] for i in res.items}) == 6
