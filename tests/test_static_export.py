import json

from fakes import settings_for

from signal_atlas.db import connect
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
    ed = json.loads((out / "api" / "edition" / "latest.json").read_text())
    assert ed["edition_date"] == "2026-11-05" and (out / "api" / "edition" / "2026-11-05.json").exists()
    assert (out / "api" / "export" / "2026-11-05.md").read_text().startswith("#")
    assert not list((out / "api").glob("series/*.json"))
