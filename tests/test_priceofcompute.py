import json
from datetime import datetime, timezone

import pytest

from signal_atlas.adapters.base import ParseError
from signal_atlas.adapters.priceofcompute import PriceOfComputeAdapter

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
SERIES = [{"day": "2026-11-07", "value": 100.5}, {"day": "2026-11-08", "value": 101.25}]


class ApiHttp:
    def __init__(self, index: object, family: object) -> None:
        self.bodies = {"index": index, "index-family?series=1": family}

    def get(self, url: str, **_: object) -> bytes:
        return json.dumps(self.bodies[url.rsplit("/", 1)[1]]).encode()


def fetch(index: object, family: object):  # type: ignore[no-untyped-def]
    return PriceOfComputeAdapter().fetch(ApiHttp(index, family), NOW)  # type: ignore[arg-type]


def _gpu(sku: str, change: object) -> dict:
    return {"sku": sku, "base_day": "2026-08-01", "base_price_usd_hr": 2.1, "change_30d_pct": change,
            "series": [{"day": "2026-11-08", "value": 97.0}]}


def test_full_payload_builds_series_and_summary():
    index = {"series": SERIES, "base_day": "2026-08-01", "latest": {"day": "2026-11-08", "value": 101.25},
             "change_7d_pct": 0.4, "change_30d_pct": -1.25}
    family = {"gpu": [_gpu("H100", 3.0), _gpu("A100", -2.0), _gpu("B200", 5.5), _gpu("L40S", 1.0)],
              "token": {"blended_usd_per_mtok": 1.8}}
    res = fetch(index, family)
    assert [s.id for s in res.series] == ["poc:composite", "poc:sku:H100", "poc:sku:A100", "poc:sku:B200",
                                          "poc:sku:L40S"]
    item = res.items[0]
    assert item.event_date == "2026-11-08"
    assert item.excerpt == ("Composite 101.25 on 2026-11-08 (base 100 = 2026-08-01). 7D +0.40%, 30D -1.25%. "
                            "Top 30D movers: B200 +5.5% 30D, H100 +3.0% 30D, L40S +1.0% 30D. "
                            "Median list token price $1.8/M (not usage-weighted).")


def test_missing_summary_fields_do_not_drop_the_series():
    index = {"series": SERIES, "base_day": "2026-08-01", "change_7d_pct": None}
    family = {"gpu": [_gpu("H100", None), "junk", {"sku": "A100", "series": []}]}
    res = fetch(index, family)
    assert [s.id for s in res.series] == ["poc:composite", "poc:sku:H100"]
    assert res.items[0].event_date == "2026-11-08"  # falls back to the last plotted day
    assert res.items[0].title == "Price of Compute GPU index — 2026-11-08"
    assert res.items[0].excerpt is None


@pytest.mark.parametrize("index,family", [([], {}), ({"series": SERIES}, []), ({"series": []}, {})])
def test_unexpected_or_empty_payload_is_a_parse_error(index, family):
    with pytest.raises(ParseError):
        fetch(index, family)
