from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signal_atlas.adapters.base import ParseError
from signal_atlas.adapters.silicondata import CODES, SiliconDataAdapter, parse_index_values

NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
NAV = ("<nav>H100 Index Daily H100 rental price index · SDH100RT H200 Index Daily H200 rental price index "
       "B300 Index Daily B300 rental price index</nav>")
CARDS = ("<section>GPU index <div>H100(SDH100RT)</div> <b>$3.06</b> <span>7.4% vs 7D</span> "
         "H100-hyperscaler $7.10 0.7% vs 7D A100(SDA100RT) $1.59 4.6% vs 7D "
         "B200(SDB200RT) $6.84 15.0% vs 7D B300 $7.67 15.3% vs 7D MI300X $2.77 4.9% vs 7D "
         "H200 $3.47 -2.7% vs 7D Token index LLM Token(SDLLMTK) $0.82 5.3% vs 7D "
         "Open LLM $0.49 1.0% vs 7D RAM index GDDR6 $19.72 1.3% vs 7D</section>")
FAQ = "<p>Licensed as SDH100RT, priced from $1,250.00 per seat.</p>"


class FakeHttp:
    def __init__(self, html: str) -> None:
        self.html = html

    def get(self, url: str, **_: object) -> bytes:
        return self.html.encode()


def test_reads_every_card_including_ones_without_a_code() -> None:
    from signal_atlas.sanitize import strip_html
    assert parse_index_values(strip_html(NAV + CARDS + FAQ)) == {
        "SDH100RT": 3.06, "SDA100RT": 1.59, "SDB200RT": 6.84, "SDB300RT": 7.67, "SDH200RT": 3.47,
        "SDLLMTK": 0.82}


def test_hyperscaler_and_non_index_cards_are_not_mistaken_for_codes() -> None:
    assert parse_index_values("H100-hyperscaler $7.10 0.7% vs 7D MI300X $2.77 4.9% vs 7D") == {}


def test_code_mentions_outside_cards_do_not_borrow_a_nearby_price() -> None:
    assert parse_index_values("SDB300RT is our B300 benchmark. Plans from $9.99 per month.") == {}


def test_fetch_records_one_point_per_index() -> None:
    res = SiliconDataAdapter().fetch(FakeHttp(NAV + CARDS), NOW)  # type: ignore[arg-type]
    assert {s.id for s in res.series} == {f"sd:{c}" for c in CODES}
    assert all(s.points == [("2026-11-12", s.points[0][1])] for s in res.series)
    assert res.warnings == []


def test_missing_indices_are_reported() -> None:
    res = SiliconDataAdapter().fetch(  # type: ignore[arg-type]
        FakeHttp("<p>A100(SDA100RT) $1.59 4.6% vs 7D</p>"), NOW)
    assert [s.id for s in res.series] == ["sd:SDA100RT"]
    assert res.warnings and "SDB300RT" in res.warnings[0] and "SDA100RT" not in res.warnings[0]


def test_unrecognised_page_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        SiliconDataAdapter().fetch(FakeHttp(NAV + FAQ), NOW)  # type: ignore[arg-type]
