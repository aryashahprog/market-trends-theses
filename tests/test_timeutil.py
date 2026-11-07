from datetime import datetime, timezone

import pytest

from signal_atlas.timeutil import iso, ny_date, parse_iso

TEN_UTC = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", [
    "2026-11-06T10:00:00Z",
    "2026-11-06T10:00:00+00:00",
    "2026-11-06T10:00:00+0000",
    "2026-11-06T05:00:00-0500",
    "2026-11-06T05:00:00-05:00",
    "2026-11-06T10:00:00.000000000Z",
    "2026-11-06 10:00:00",
    "Fri, 06 Nov 2026 10:00:00 GMT",
    "Fri, 06 Nov 2026 05:00:00 -0500",
])
def test_parse_iso_keeps_time_of_day_across_common_formats(value):
    assert parse_iso(value) == TEN_UTC


def test_parse_iso_keeps_fraction_up_to_microseconds():
    dt = parse_iso("2026-11-06T10:00:00.123456789Z")
    assert dt is not None and dt.microsecond == 123456


def test_parse_iso_date_only_and_invalid():
    assert parse_iso("2026-11-06") == datetime(2026, 11, 6, tzinfo=timezone.utc)
    assert parse_iso("2026-11-06Tgarbage") == datetime(2026, 11, 6, tzinfo=timezone.utc)
    assert parse_iso("not a date") is None
    assert parse_iso("") is None
    assert parse_iso(None) is None


def test_offset_timestamps_land_on_the_right_new_york_day():
    late_evening = parse_iso("2026-11-06T23:30:00-0500")
    assert late_evening is not None
    assert ny_date(late_evening) == "2026-11-06"
    assert iso(late_evening) == "2026-11-07T04:30:00Z"
