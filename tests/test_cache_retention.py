import sqlite3

import httpx
from fakes import Good, null_fetcher, settings_for

from signal_atlas.db import connect, pack_for_publication
from signal_atlas.fetcher import CACHE_RETENTION_S, Fetcher, prune_cache
from signal_atlas.pipeline import run_pipeline
from signal_atlas.seed import seed

PAGE = b"<html>" + b"x" * 200_000 + b"</html>"


def _cache(conn, url, fetched_at, body=PAGE):
    conn.execute("INSERT INTO http_cache(url, etag, last_modified, fetched_at, status, body) VALUES (?,?,?,?,?,?)",
                 (url, None, None, fetched_at, 200, body))


def _urls(conn):
    return {r[0] for r in conn.execute("SELECT url FROM http_cache")}


def test_prune_drops_only_entries_past_retention(tmp_path):
    conn = connect(tmp_path / "c.db")
    now = 1_800_000_000.0
    _cache(conn, "https://a.example/old", now - CACHE_RETENTION_S - 1)
    _cache(conn, "https://a.example/recent", now - CACHE_RETENTION_S + 60)
    assert prune_cache(conn, now) == 1
    assert _urls(conn) == {"https://a.example/recent"}


def test_retention_outlasts_the_longest_adapter_ttl(tmp_path):
    clock = [1_800_000_000.0]
    hits: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(req.url.path)
        return httpx.Response(200, text="" if req.url.path == "/robots.txt" else "page")

    conn = connect(tmp_path / "c.db")
    f = Fetcher(conn, "t", transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: clock[0])
    f.get("https://a.example/p", ttl_s=24 * 3600)
    clock[0] += 23 * 3600
    prune_cache(conn, clock[0])
    assert f.get("https://a.example/p", ttl_s=24 * 3600) == b"page"
    assert hits.count("/p") == 1  # still served from cache: pruning never defeats a live TTL


def test_ingest_run_prunes_stale_cache(tmp_path):
    s = settings_for(tmp_path)
    conn = connect(s.db_path)
    seed(conn)
    fetcher = null_fetcher(conn)
    now = fetcher.clock()
    _cache(conn, "https://a.example/stale", now - 30 * 86400)
    _cache(conn, "https://a.example/fresh", now - 3600)
    assert run_pipeline(conn, s, "cli", adapters=[Good()], fetcher=fetcher)["status"] == "success"
    assert _urls(conn) == {"https://a.example/fresh"}


def test_pack_removes_cached_pages_and_shrinks_the_file(tmp_path):
    path = tmp_path / "p.db"
    conn = connect(path)
    seed(conn)
    for i in range(20):
        _cache(conn, f"https://a.example/{i}", 1_800_000_000.0)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = path.stat().st_size
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    pack_for_publication(conn)
    conn.close()
    assert path.stat().st_size < before - 3_000_000
    assert not (tmp_path / "p.db-wal").exists()
    c = sqlite3.connect(path)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert c.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == docs > 0
