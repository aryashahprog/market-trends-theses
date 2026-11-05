import httpx
import pytest
from fakes import Boom, Good, null_fetcher, settings_for

from signal_atlas.db import connect
from signal_atlas.fetcher import Fetcher, FetchError
from signal_atlas.pipeline import acquire_lock, get_status, run_pipeline
from signal_atlas.seed import seed


def _setup(tmp_path):
    s = settings_for(tmp_path)
    conn = connect(s.db_path)
    seed(conn)
    return s, conn


def test_partial_failure_keeps_going_and_snapshots(tmp_path):
    s, conn = _setup(tmp_path)
    r = run_pipeline(conn, s, "cli", adapters=[Good(), Boom()], fetcher=null_fetcher(conn))
    assert r["status"] == "partial"
    by = {x["source"]: x for x in r["sources"]}
    assert by["good"]["new"] == 1 and by["boom"]["status"] == "failed" and "not bypassed" in by["boom"]["error"]
    st = get_status(conn, s)
    assert st["last_success_at"] is not None
    assert {x["id"]: x["last_status"] for x in st["sources"]}["boom"] == "failed"
    doc = conn.execute("SELECT excerpt FROM documents WHERE source_id='good'").fetchone()
    assert "<" not in doc["excerpt"] and "alert" not in doc["excerpt"]  # untrusted markup stripped


def test_failed_source_preserves_prior_good_data(tmp_path):
    s, conn = _setup(tmp_path)
    assert run_pipeline(conn, s, "cli", adapters=[Good()], fetcher=null_fetcher(conn))["status"] == "success"
    snaps = conn.execute("SELECT COUNT(*) FROM edition_snapshots").fetchone()[0]
    r = run_pipeline(conn, s, "cli", adapters=[Good(title="Changed headline", broken_series=True), Boom()],
                     fetcher=null_fetcher(conn))
    assert r["status"] == "failed"
    title = conn.execute("SELECT title FROM documents WHERE source_id='good'").fetchone()["title"]
    assert title.startswith("Nvidia GPU rental")  # rolled back, prior data intact
    assert conn.execute("SELECT COUNT(*) FROM series_points WHERE series_id='test:idx'").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM edition_snapshots").fetchone()[0] == snaps  # no snapshot from a failed run
    assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 6


def test_overlapping_runs_are_skipped(tmp_path):
    s, conn = _setup(tmp_path)
    assert acquire_lock(conn, "ingest", "other", ttl_s=60)
    assert run_pipeline(conn, s, "scheduled", adapters=[Good()], fetcher=null_fetcher(conn))["status"] == "skipped"


def test_new_documents_matched_to_signals_as_unreviewed(tmp_path):
    s, conn = _setup(tmp_path)
    run_pipeline(conn, s, "cli", adapters=[Good()], fetcher=null_fetcher(conn))
    m = conn.execute("SELECT signal_id FROM signal_matches").fetchall()
    assert "gpu-rent-vs-token-deflation" in {r["signal_id"] for r in m}
    ev = conn.execute("SELECT COUNT(*) FROM signal_evidence e JOIN documents d ON d.id=e.document_id "
                      "WHERE d.source_id='good'").fetchone()[0]
    assert ev == 0  # matches never become evidence automatically


def test_fetcher_respects_robots_paywalls_and_cache(tmp_path):
    conn = connect(tmp_path / "f.db")
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        if req.url.path == "/paywall":
            return httpx.Response(403)
        return httpx.Response(200, text="ok", headers={"etag": '"v1"'})

    f = Fetcher(conn, "SignalAtlasTest", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(FetchError, match="robots"):
        f.get("https://x.example/private/a")
    with pytest.raises(FetchError, match="not bypassed"):
        f.get("https://x.example/paywall")
    assert f.get("https://x.example/ok") == b"ok"
    n = len(calls)
    assert f.get("https://x.example/ok") == b"ok" and len(calls) == n  # served from cache within TTL
