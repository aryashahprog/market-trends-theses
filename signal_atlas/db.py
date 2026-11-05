from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, homepage TEXT,
  access_note TEXT, last_success_at TEXT, last_error TEXT, last_error_at TEXT, last_status TEXT);
CREATE TABLE IF NOT EXISTS clusters(
  id INTEGER PRIMARY KEY, label TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, canonical_url TEXT NOT NULL UNIQUE, url TEXT NOT NULL,
  source_id TEXT NOT NULL, source_type TEXT NOT NULL, title TEXT NOT NULL, excerpt TEXT,
  published_at TEXT, event_date TEXT, first_seen_at TEXT NOT NULL, retrieved_at TEXT NOT NULL,
  content_hash TEXT NOT NULL, cluster_id INTEGER REFERENCES clusters(id),
  meta TEXT NOT NULL DEFAULT '{}', origin TEXT NOT NULL DEFAULT 'ingested');
CREATE INDEX IF NOT EXISTS idx_docs_first_seen ON documents(first_seen_at);
CREATE TABLE IF NOT EXISTS document_revisions(
  id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
  retrieved_at TEXT NOT NULL, content_hash TEXT NOT NULL, title TEXT, excerpt TEXT);
CREATE TABLE IF NOT EXISTS series(
  id TEXT PRIMARY KEY, label TEXT NOT NULL, unit TEXT, source_url TEXT NOT NULL,
  attribution TEXT NOT NULL, method TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS series_points(
  series_id TEXT NOT NULL REFERENCES series(id), day TEXT NOT NULL, value REAL NOT NULL,
  retrieved_at TEXT NOT NULL, PRIMARY KEY(series_id, day));
CREATE TABLE IF NOT EXISTS signals(
  id TEXT PRIMARY KEY, data TEXT NOT NULL, first_published_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'published');
CREATE TABLE IF NOT EXISTS signal_evidence(
  id INTEGER PRIMARY KEY, signal_id TEXT NOT NULL REFERENCES signals(id),
  document_id INTEGER NOT NULL REFERENCES documents(id),
  claim_type TEXT NOT NULL CHECK(claim_type IN ('reported','corroborated','primary')),
  stance TEXT NOT NULL CHECK(stance IN ('supports','challenges','context')),
  statement TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0,
  UNIQUE(signal_id, document_id, statement));
CREATE TABLE IF NOT EXISTS signal_revisions(
  id INTEGER PRIMARY KEY, signal_id TEXT NOT NULL, revised_at TEXT NOT NULL, reason TEXT,
  data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signal_matches(
  signal_id TEXT NOT NULL, document_id INTEGER NOT NULL, terms TEXT NOT NULL,
  matched_at TEXT NOT NULL, PRIMARY KEY(signal_id, document_id));
CREATE TABLE IF NOT EXISTS edition_notes(
  edition_date TEXT PRIMARY KEY, headline TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_runs(
  id INTEGER PRIMARY KEY, trigger TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS source_runs(
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
  source_id TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
  items_seen INTEGER NOT NULL DEFAULT 0, items_new INTEGER NOT NULL DEFAULT 0,
  items_updated INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS edition_snapshots(
  id INTEGER PRIMARY KEY, edition_date TEXT NOT NULL, run_id INTEGER, created_at TEXT NOT NULL,
  payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_snap_date ON edition_snapshots(edition_date, created_at);
CREATE TABLE IF NOT EXISTS http_cache(
  url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, fetched_at REAL NOT NULL,
  status INTEGER NOT NULL, body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS locks(name TEXT PRIMARY KEY, holder TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS heartbeats(name TEXT PRIMARY KEY, at TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS rate_events(key TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_rate ON rate_events(key, at);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(edition_notes)")}
    if "takeaways" not in cols:
        conn.execute("ALTER TABLE edition_notes ADD COLUMN takeaways TEXT")


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def loads(s: str | None) -> Any:
    return json.loads(s) if s else None
