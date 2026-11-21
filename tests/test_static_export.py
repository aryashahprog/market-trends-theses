import json
from datetime import datetime, timezone

from fakes import settings_for

from signal_atlas.adapters.base import SeriesUpdate
from signal_atlas.db import connect
from signal_atlas.pipeline import upsert_series, write_snapshot
from signal_atlas.seed import seed
from signal_atlas.static_export import export_site


def test_static_export_writes_read_only_site(tmp_path):
    s = settings_for(tmp_path)
    conn = connect(s.db_path)
    seed(conn)
    out = tmp_path / "site"
    r = export_site(conn, s, out)
    assert r["editions"] == 1 and r["series"] == 0  # no series ingested -> no chart files fabricated
    html = (out / "index.html").read_text()
    assert 'data-mode="static"' in html and '"/static/' not in html and "Content-Security-Policy" in html
    assert "url(/static/" not in (out / "static" / "styles.css").read_text()
    st = json.loads((out / "api" / "status.json").read_text())
    assert st["mode"] == "static" and st["manual_refresh_enabled"] is False
    assert len(st["slots"]) == 14 and st["slots"][0] == st["next_scheduled"] and st["slots"] == sorted(st["slots"])
    assert st["slots"][0] > st["now"]
    ed = json.loads((out / "api" / "edition" / "latest.json").read_text())
    assert ed["edition_date"] == "2026-11-05" and (out / "api" / "edition" / "2026-11-05.json").exists()
    assert (out / "api" / "export" / "2026-11-05.md").read_text().startswith("#")
    assert not list((out / "api").glob("series/*.json"))


def test_export_keeps_captured_chart_values_and_excludes_future_data(tmp_path):
    s = settings_for(tmp_path)
    conn = connect(s.db_path)
    seed(conn)
    series = SeriesUpdate("poc:composite", "GPU index", "index", "https://example.com", "Example", "Test",
                          [("2026-11-05", 100), ("2026-11-06", 110), ("2026-11-07", 200)])
    upsert_series(conn, series, "2026-11-06T14:00:00Z")
    write_snapshot(conn, None, datetime(2026, 11, 6, 15, tzinfo=timezone.utc))

    series.points = [("2026-11-06", 111), ("2026-11-07", 120)]
    upsert_series(conn, series, "2026-11-07T14:00:00Z")
    write_snapshot(conn, None, datetime(2026, 11, 7, 15, tzinfo=timezone.utc))
    # Legacy payloads didn't record a chart series. Export must not backfill them with live values.
    conn.execute("UPDATE edition_snapshots SET payload=json_remove(payload, '$.chart_series') "
                 "WHERE edition_date='2026-11-05'")

    out = tmp_path / "site"
    export_site(conn, s, out)
    editions = out / "api" / "edition"
    legacy = json.loads((editions / "2026-11-05.json").read_text())
    assert "chart_series" not in legacy
    archived = json.loads((editions / "2026-11-06.json").read_text())
    assert archived["chart_series"][series.id]["points"] == [
        {"day": "2026-11-05", "value": 100}, {"day": "2026-11-06", "value": 110},
    ]
    latest = json.loads((editions / "latest.json").read_text())
    assert latest["chart_series"][series.id]["points"][-2:] == [
        {"day": "2026-11-06", "value": 111}, {"day": "2026-11-07", "value": 120},
    ]
