"""Static export: the same site and read-only API as JSON files, for static hosting (e.g. GitHub Pages)."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .config import Settings
from .export import edition_markdown
from .pipeline import get_series, get_status, latest_snapshot, list_editions, recent_leads

STATIC = Path(__file__).parent / "static"
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'")


def safe_id(sid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", sid)


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"), default=str)
    path.write_text(text, "utf-8")


def export_site(conn: sqlite3.Connection, settings: Settings, out: Path) -> dict[str, int]:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out / "static")
    html = (STATIC / "index.html").read_text("utf-8")
    html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    html = html.replace('<html lang="en">', '<html lang="en" data-mode="static">')
    html = html.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="{CSP}">')
    _write(out / "index.html", html)
    css = out / "static" / "styles.css"
    css.write_text(css.read_text("utf-8").replace("url(/static/fonts/", "url(fonts/"), "utf-8")
    _write(out / ".nojekyll", "")

    status = get_status(conn, settings)
    status.update(mode="static", manual_refresh_enabled=False, running=False,
                  stale_grace_minutes=settings.stale_grace_minutes)
    _write(out / "api" / "status.json", status)
    editions = list_editions(conn)
    _write(out / "api" / "editions.json", editions)
    series_ids: set[str] = set()
    for e in editions:
        snap = latest_snapshot(conn, e["edition_date"])
        if not snap:
            continue
        _write(out / "api" / "edition" / f"{e['edition_date']}.json", snap)
        _write(out / "api" / "export" / f"{e['edition_date']}.md", edition_markdown(snap))
        series_ids.update(sid for s in snap["signals"] if s.get("chart") for sid in s["chart"]["series"])
    latest = latest_snapshot(conn)
    if latest:
        _write(out / "api" / "edition" / "latest.json", latest)
    written = 0
    for sid in sorted(series_ids):
        series = get_series(conn, sid)
        if series:  # never write a placeholder for a series that has not been ingested
            _write(out / "api" / "series" / f"{safe_id(sid)}.json", series)
            written += 1
    leads = recent_leads(conn, 3, 120)
    _write(out / "api" / "leads.json", leads)
    return {"editions": len(editions), "series": written, "leads": len(leads)}
