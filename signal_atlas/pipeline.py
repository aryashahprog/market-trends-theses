from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from datetime import time as dtime
from typing import Any

from .adapters.base import Adapter, RawItem, SeriesUpdate
from .cluster import assign_cluster
from .config import Settings
from .db import dumps, loads, tx
from .fetcher import Fetcher
from .ranking import METHOD, score_signal
from .sanitize import clean_text, content_hash
from .scheduling import is_stale, next_slot, previous_slot
from .timeutil import NY, iso, ny_date, parse_iso, utcnow
from .urlnorm import canonicalize

log = logging.getLogger("signal_atlas.pipeline")
INGEST_TRIGGERS = ("scheduled", "manual", "cli", "catch-up")


# ---------- documents & series ----------

def ensure_source(conn: sqlite3.Connection, a: Adapter) -> None:
    conn.execute(
        "INSERT INTO sources(id, name, kind, homepage, access_note) VALUES (?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind, homepage=excluded.homepage, "
        "access_note=excluded.access_note",
        (a.id, a.name, a.kind, a.homepage, a.access_note),
    )


def upsert_document(conn: sqlite3.Connection, item: RawItem, source_id: str, now_iso: str,
                    origin: str = "ingested") -> tuple[int, str]:
    canon = canonicalize(item.url)
    title = clean_text(item.title, 200) or canon
    excerpt = clean_text(item.excerpt, 300) or None
    h = content_hash(title, excerpt, item.event_date)
    row = conn.execute("SELECT id, content_hash FROM documents WHERE canonical_url=?", (canon,)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO documents(canonical_url, url, source_id, source_type, title, excerpt, published_at, "
            "event_date, first_seen_at, retrieved_at, content_hash, meta, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (canon, item.url, source_id, item.source_type, title, excerpt, item.published_at, item.event_date,
             now_iso, now_iso, h, dumps(item.meta), origin),
        )
        doc_id = int(cur.lastrowid or 0)
        conn.execute("INSERT INTO document_revisions(document_id, retrieved_at, content_hash, title, excerpt) "
                     "VALUES (?,?,?,?,?)", (doc_id, now_iso, h, title, excerpt))
        assign_cluster(conn, doc_id, title, now_iso)
        return doc_id, "new"
    doc_id = int(row["id"])
    if row["content_hash"] != h:
        conn.execute(
            "UPDATE documents SET title=?, excerpt=?, published_at=COALESCE(?, published_at), "
            "event_date=COALESCE(?, event_date), retrieved_at=?, content_hash=?, meta=? WHERE id=?",
            (title, excerpt, item.published_at, item.event_date, now_iso, h, dumps(item.meta), doc_id),
        )
        conn.execute("INSERT INTO document_revisions(document_id, retrieved_at, content_hash, title, excerpt) "
                     "VALUES (?,?,?,?,?)", (doc_id, now_iso, h, title, excerpt))
        return doc_id, "updated"
    conn.execute("UPDATE documents SET retrieved_at=? WHERE id=?", (now_iso, doc_id))
    return doc_id, "unchanged"


def upsert_series(conn: sqlite3.Connection, s: SeriesUpdate, now_iso: str) -> None:
    conn.execute(
        "INSERT INTO series(id, label, unit, source_url, attribution, method, updated_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET label=excluded.label, unit=excluded.unit, source_url=excluded.source_url, "
        "attribution=excluded.attribution, method=excluded.method, updated_at=excluded.updated_at",
        (s.id, s.label, s.unit, s.source_url, s.attribution, s.method, now_iso),
    )
    conn.executemany(
        "INSERT INTO series_points(series_id, day, value, retrieved_at) VALUES (?,?,?,?) "
        "ON CONFLICT(series_id, day) DO UPDATE SET value=excluded.value, retrieved_at=excluded.retrieved_at",
        [(s.id, d, v, now_iso) for d, v in s.points],
    )


def get_series(conn: sqlite3.Connection, sid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM series WHERE id=?", (sid,)).fetchone()
    if not row:
        return None
    pts = conn.execute("SELECT day, value FROM series_points WHERE series_id=? ORDER BY day", (sid,)).fetchall()
    return {**dict(row), "points": [{"day": p["day"], "value": p["value"]} for p in pts]}


# ---------- signals ----------

def load_signals(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or utcnow()
    since = iso(now - timedelta(days=7))
    out = []
    for r in conn.execute("SELECT * FROM signals WHERE status='published' ORDER BY id"):
        sig = loads(r["data"])
        sig.update(id=r["id"], first_published_at=r["first_published_at"], updated_at=r["updated_at"])
        sig["evidence"] = [dict(e) for e in conn.execute(
            "SELECT e.claim_type, e.stance, e.statement, d.url, d.canonical_url, d.title, d.source_type, "
            "d.published_at, d.event_date, d.first_seen_at, d.retrieved_at, s.name AS source_name "
            "FROM signal_evidence e JOIN documents d ON d.id=e.document_id LEFT JOIN sources s ON s.id=d.source_id "
            "WHERE e.signal_id=? ORDER BY e.position, e.id", (r["id"],))]
        mentions = [dict(m) for m in conn.execute(
            "SELECT m.terms, m.matched_at, d.url, d.title, d.source_type, d.published_at, d.first_seen_at, "
            "s.name AS source_name FROM signal_matches m JOIN documents d ON d.id=m.document_id "
            "LEFT JOIN sources s ON s.id=d.source_id WHERE m.signal_id=? ORDER BY m.matched_at DESC, d.id DESC LIMIT 12",
            (r["id"],))]
        for m in mentions:
            m["terms"] = loads(m["terms"])
        sig["unreviewed_mentions"] = mentions
        sig["mentions_7d"] = conn.execute(
            "SELECT COUNT(*) FROM signal_matches WHERE signal_id=? AND matched_at>=?", (r["id"], since)).fetchone()[0]
        sig["revision_count"] = conn.execute(
            "SELECT COUNT(*) FROM signal_revisions WHERE signal_id=?", (r["id"],)).fetchone()[0]
        out.append(sig)
    return out


def _has(term: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", text) is not None


def match_rule(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("match"):
        return dict(data["match"])
    return {"anchors": data.get("match_terms") or [], "context": [], "min_terms": int(data.get("match_min", 2)),
            "topic": data.get("title", "this thesis")}  # pre-v2 records


def match_document(text: str, rule: dict[str, Any]) -> dict[str, Any] | None:
    """A lead matches only when it names a thesis-specific anchor term plus enough distinct supporting terms,
    and none of the thesis's exclusion terms. Broad keyword overlap alone is not a match."""
    text = text.lower()
    if any(_has(t, text) for t in rule.get("exclude", [])):
        return None
    anchors = [t for t in rule.get("anchors", []) if _has(t, text)]
    if not anchors:
        return None
    context = [t for t in rule.get("context", []) if t not in anchors and _has(t, text)]
    if len(anchors) + len(context) < int(rule.get("min_terms", 2)):
        return None
    why = f"Names {', '.join(anchors)}" + (f" alongside {', '.join(context)}" if context else "")
    return {"anchors": anchors, "context": context, "why": f"{why}; may bear on {rule.get('topic', 'this thesis')}."}


def match_signals(conn: sqlite3.Connection, doc_ids: Sequence[int], now_iso: str, prune: bool = False) -> int:
    """Record unreviewed thesis mentions. With prune=True, existing matches that no longer satisfy the
    current rule are removed (their original matched_at is kept for those that still qualify)."""
    if not doc_ids:
        return 0
    sigs = [(r["id"], match_rule(loads(r["data"]))) for r in conn.execute("SELECT id, data FROM signals WHERE status='published'")]
    n = 0
    for doc_id in doc_ids:
        d = conn.execute("SELECT title, excerpt FROM documents WHERE id=?", (doc_id,)).fetchone()
        text = f"{d['title']} {d['excerpt'] or ''}"
        for sid, rule in sigs:
            hit = match_document(text, rule)
            existing = conn.execute("SELECT 1 FROM signal_matches WHERE signal_id=? AND document_id=?",
                                    (sid, doc_id)).fetchone()
            if not hit:
                if prune and existing:
                    conn.execute("DELETE FROM signal_matches WHERE signal_id=? AND document_id=?", (sid, doc_id))
                continue
            if conn.execute("SELECT 1 FROM signal_evidence WHERE signal_id=? AND document_id=?", (sid, doc_id)).fetchone():
                continue  # already reviewed evidence; never listed again as an unreviewed mention
            if existing:
                conn.execute("UPDATE signal_matches SET terms=? WHERE signal_id=? AND document_id=?", (dumps(hit), sid, doc_id))
            else:
                n += conn.execute("INSERT INTO signal_matches(signal_id, document_id, terms, matched_at) VALUES (?,?,?,?)",
                                  (sid, doc_id, dumps(hit), now_iso)).rowcount
    return n


def rematch_ingested(conn: sqlite3.Connection, now_iso: str) -> int:
    ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE origin='ingested'")]
    return match_signals(conn, ids, now_iso, prune=True)


# ---------- editions ----------

def _ny_day_bounds(day: str) -> tuple[str, str]:
    d = datetime.strptime(day, "%Y-%m-%d").date()
    start = datetime.combine(d, dtime(0), tzinfo=NY)
    return iso(start), iso(start + timedelta(days=1))


def build_edition(conn: sqlite3.Connection, edition_date: str, now: datetime, run_id: int | None) -> dict[str, Any]:
    signals = load_signals(conn, now)
    for s in signals:
        s["scores"] = score_signal(s, now)
        fp = parse_iso(s["first_published_at"])
        s["is_new_in_edition"] = bool(fp and ny_date(fp) == edition_date)
    signals.sort(key=lambda s: (-s["scores"]["composite"], s["id"]))
    for i, s in enumerate(signals, 1):
        s["rank"] = i
    start, end = _ny_day_bounds(edition_date)
    leads_new = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE origin='ingested' AND first_seen_at>=? AND first_seen_at<?",
        (start, end)).fetchone()[0]
    note_row = conn.execute("SELECT headline, summary, takeaways FROM edition_notes WHERE edition_date=?",
                            (edition_date,)).fetchone()
    if note_row:
        note = {"headline": note_row["headline"], "summary": note_row["summary"],
                "takeaways": loads(note_row["takeaways"]) or [], "auto": False}
    else:
        new = [s for s in signals if s["is_new_in_edition"]]
        last = conn.execute("SELECT headline, summary, takeaways FROM edition_notes WHERE edition_date<? "
                            "ORDER BY edition_date DESC LIMIT 1",
                            (edition_date,)).fetchone()
        note = {
            "headline": f"{len(new)} new thesis{'es' if len(new) != 1 else ''} today"
            if new else (last["headline"] if last else signals[0]["title"] if signals else "No theses published yet"),
            "summary": last["summary"] if last and not new else "",
            "takeaways": (loads(last["takeaways"]) or []) if last and not new else [s["title"] for s in signals[:3]],
            "auto": not (last and not new),
        }
    prev = conn.execute("SELECT edition_date, payload FROM edition_snapshots WHERE edition_date<? "
                        "ORDER BY edition_date DESC, created_at DESC, id DESC LIMIT 1", (edition_date,)).fetchone()
    if prev:
        prev_sigs = {p["id"]: p for p in loads(prev["payload"])["signals"]}
        for s in signals:
            ch = since_last(prev_sigs.get(s["id"]), s, prev["edition_date"])
            if ch:
                s["since_last"] = ch
    return {"edition_date": edition_date, "generated_at": iso(now), "run_id": run_id, "note": note,
            "signals": signals, "leads_new": leads_new, "ranking": METHOD}


def since_last(prev: dict[str, Any] | None, cur: dict[str, Any], prev_date: str) -> dict[str, Any] | None:
    """Changes recorded between a thesis in the previous edition and now. Returns None when nothing changed."""
    if not prev:
        return None
    seen = {e["statement"] for e in prev.get("evidence", [])}
    new_ev = [{k: e.get(k) for k in ("statement", "claim_type", "stance", "url", "source_name")}
              for e in cur.get("evidence", []) if e["statement"] not in seen]
    revised = [{"what": label, "from": prev.get(k), "to": cur.get(k)}
               for k, label in (("title", "Headline"), ("takeaway", "Takeaway"), ("direction", "Direction"))
               if prev.get(k) and cur.get(k) and prev.get(k) != cur.get(k)]
    conf = ({"from": prev.get("confidence"), "to": cur.get("confidence")}
            if prev.get("confidence") and prev.get("confidence") != cur.get("confidence") else None)
    outcomes = [v for v in cur.get("validation_log") or [] if str(v.get("date", "")) > prev_date]
    if not (new_ev or revised or conf or outcomes):
        return None
    return {"previous_edition": prev_date, "new_evidence": new_ev, "revised": revised, "confidence": conf,
            "validation_outcomes": outcomes, "open_questions": [cur["next_validation"]] if cur.get("next_validation") else []}


def write_snapshot(conn: sqlite3.Connection, run_id: int | None, now: datetime,
                   edition_date: str | None = None) -> dict[str, Any]:
    day = edition_date or ny_date(now)
    payload = build_edition(conn, day, now, run_id)
    conn.execute("INSERT INTO edition_snapshots(edition_date, run_id, created_at, payload) VALUES (?,?,?,?)",
                 (day, run_id, iso(now), dumps(payload)))
    return payload


def latest_snapshot(conn: sqlite3.Connection, edition_date: str | None = None) -> dict[str, Any] | None:
    if edition_date:
        row = conn.execute("SELECT payload, created_at FROM edition_snapshots WHERE edition_date=? "
                           "ORDER BY created_at DESC, id DESC LIMIT 1", (edition_date,)).fetchone()
    else:
        row = conn.execute("SELECT payload, created_at FROM edition_snapshots "
                           "ORDER BY edition_date DESC, created_at DESC, id DESC LIMIT 1").fetchone()
    if not row:
        return None
    payload: dict[str, Any] = loads(row["payload"])
    payload["snapshot_created_at"] = row["created_at"]
    return payload


def list_editions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT edition_date, COUNT(*) AS snapshots, MAX(created_at) AS last_updated FROM edition_snapshots "
        "GROUP BY edition_date ORDER BY edition_date DESC")]


# ---------- locking & runs ----------

def acquire_lock(conn: sqlite3.Connection, name: str, holder: str, ttl_s: float) -> bool:
    now = time.time()
    with tx(conn):
        r = conn.execute("SELECT expires_at FROM locks WHERE name=?", (name,)).fetchone()
        if r and r["expires_at"] > now:
            return False
        conn.execute("INSERT INTO locks(name, holder, expires_at) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
                     "holder=excluded.holder, expires_at=excluded.expires_at", (name, holder, now + ttl_s))
    return True


def release_lock(conn: sqlite3.Connection, name: str, holder: str) -> None:
    conn.execute("DELETE FROM locks WHERE name=? AND holder=?", (name, holder))


def lock_held(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute("SELECT expires_at FROM locks WHERE name=?", (name,)).fetchone()
    return bool(r and r["expires_at"] > time.time())


def run_pipeline(conn: sqlite3.Connection, settings: Settings, trigger: str,
                 adapters: Sequence[Adapter] | None = None, fetcher: Fetcher | None = None,
                 clock: Callable[[], datetime] = utcnow) -> dict[str, Any]:
    if adapters is None:
        from .adapters import default_adapters
        adapters = default_adapters(settings)
    holder = f"{trigger}-{os.getpid()}-{time.time():.3f}"
    if not acquire_lock(conn, "ingest", holder, ttl_s=1800):
        return {"status": "skipped", "reason": "another ingestion run is in progress"}
    own_fetcher = fetcher is None
    http = fetcher or Fetcher(conn, settings.http_user_agent)
    started = clock()
    run_id = int(conn.execute("INSERT INTO pipeline_runs(trigger, started_at, status) VALUES (?,?, 'running')",
                              (trigger, iso(started))).lastrowid or 0)
    results: list[dict[str, Any]] = []
    new_ids: list[int] = []
    try:
        for a in adapters:
            ensure_source(conn, a)
        for a in adapters:
            t0 = iso(clock())
            sr = int(conn.execute("INSERT INTO source_runs(run_id, source_id, started_at, status) VALUES (?,?,?,'running')",
                                  (run_id, a.id, t0)).lastrowid or 0)
            counts = {"seen": 0, "new": 0, "updated": 0}
            try:
                res = a.fetch(http, clock())
                now_iso = iso(clock())
                with tx(conn):  # all-or-nothing per source: a failure never half-overwrites prior good data
                    for item in res.items:
                        doc_id, state = upsert_document(conn, item, a.id, now_iso)
                        counts["seen"] += 1
                        if state in ("new", "updated"):
                            counts[state] += 1
                        if state == "new":
                            new_ids.append(doc_id)
                    for s in res.series:
                        upsert_series(conn, s, now_iso)
                status = "degraded" if res.warnings else "ok"
                err = "; ".join(res.warnings)[:500] or None
                conn.execute("UPDATE sources SET last_success_at=?, last_status=? WHERE id=?", (now_iso, status, a.id))
            except Exception as e:  # recoverable: record and continue with other sources
                status, err = "failed", f"{type(e).__name__}: {e}"[:500]
                log.warning("source %s failed: %s", a.id, err)
                conn.execute("UPDATE sources SET last_error=?, last_error_at=?, last_status='failed' WHERE id=?",
                             (err, iso(clock()), a.id))
            conn.execute("UPDATE source_runs SET finished_at=?, status=?, items_seen=?, items_new=?, items_updated=?, "
                         "error=? WHERE id=?", (iso(clock()), status, counts["seen"], counts["new"],
                                                 counts["updated"], err, sr))
            results.append({"source": a.id, "status": status, **counts, "error": err})
        failed = sum(r["status"] == "failed" for r in results)
        overall = "failed" if results and failed == len(results) else ("partial" if failed else "success")
        matched = 0
        if overall != "failed":
            with tx(conn):
                matched = match_signals(conn, new_ids, iso(clock()))
                write_snapshot(conn, run_id, clock())
        summary = {"sources": results, "new_documents": len(new_ids), "new_mentions": matched,
                   "requests": http.requests_made}
        conn.execute("UPDATE pipeline_runs SET finished_at=?, status=?, summary=? WHERE id=?",
                     (iso(clock()), overall, dumps(summary), run_id))
        return {"run_id": run_id, "status": overall, **summary}
    except Exception as e:
        conn.execute("UPDATE pipeline_runs SET finished_at=?, status='failed', summary=? WHERE id=?",
                     (iso(clock()), dumps({"error": f"{type(e).__name__}: {e}"[:500], "sources": results}), run_id))
        log.exception("pipeline run failed")
        return {"run_id": run_id, "status": "failed", "error": str(e)}
    finally:
        release_lock(conn, "ingest", holder)
        if own_fetcher:
            http.close()


# ---------- status ----------

def plain_error(err: str | None) -> str:
    """Reader-facing reason for a source problem; the raw error stays in diagnostics."""
    e = (err or "").lower()
    if "sec_user_agent" in e or "contact" in e:
        return "not configured: SEC requests need a contact address"
    if "robots" in e:
        return "skipped: the site's robots.txt does not allow this page"
    if any(c in e for c in ("401", "402", "403", "access restricted", "not bypassed", "paywall")):
        return "access restricted by the publisher (not bypassed)"
    if "429" in e or "rate limit" in e:
        return "rate-limited by the source; retried next run"
    if "timeout" in e or "timed out" in e:
        return "timed out; retried next run"
    if "parse" in e:
        return "returned data in an unexpected format"
    return "unavailable this run; retried next run"


def get_status(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    q = ",".join("?" * len(INGEST_TRIGGERS))
    last_run = conn.execute(f"SELECT * FROM pipeline_runs WHERE trigger IN ({q}) ORDER BY id DESC LIMIT 1",
                            INGEST_TRIGGERS).fetchone()
    last_ok = conn.execute(f"SELECT finished_at FROM pipeline_runs WHERE trigger IN ({q}) AND status IN "
                           "('success','partial') ORDER BY id DESC LIMIT 1", INGEST_TRIGGERS).fetchone()
    last_ok_dt = parse_iso(last_ok["finished_at"]) if last_ok else None
    grace = timedelta(minutes=settings.stale_grace_minutes)
    hb = conn.execute("SELECT at, detail FROM heartbeats WHERE name='scheduler'").fetchone()
    hb_at = parse_iso(hb["at"]) if hb else None
    sources = [dict(r) for r in conn.execute(
        "SELECT id, name, kind, homepage, access_note, last_success_at, last_error, last_error_at, last_status "
        "FROM sources ORDER BY kind, name")]
    for src in sources:
        src["plain_error"] = plain_error(src["last_error"]) if src["last_status"] in ("failed", "degraded") else None
    run, refresh = None, None
    if last_run:
        run = dict(last_run)
        run["summary"] = loads(run["summary"])
        rows = (run["summary"] or {}).get("sources") or []
        if rows:
            names = {x["id"]: x["name"] for x in sources}
            refresh = {"status": run["status"], "finished_at": run["finished_at"], "total": len(rows),
                       "ok": sum(r["status"] == "ok" for r in rows),
                       "issues": [{"source": names.get(r["source"], r["source"]), "status": r["status"],
                                   "reason": plain_error(r.get("error"))} for r in rows
                                  if r["status"] in ("failed", "degraded")]}
    return {
        "now": iso(now),
        "timezone": "America/New_York",
        "schedule": "08:00 and 16:00 America/New_York daily",
        "next_scheduled": iso(next_slot(now)),
        "previous_slot": iso(previous_slot(now)),
        "last_run": run,
        "refresh_summary": refresh,
        "last_success_at": iso(last_ok_dt) if last_ok_dt else None,
        "stale": is_stale(last_ok_dt, now, grace),
        "stale_grace_minutes": settings.stale_grace_minutes,
        "scheduler": {
            "heartbeat_at": iso(hb_at) if hb_at else None,
            "alive": bool(hb_at and now - hb_at < timedelta(minutes=5)),
            "detail": loads(hb["detail"]) if hb and hb["detail"] else None,
        },
        "manual_refresh_enabled": bool(settings.admin_token),
        "running": lock_held(conn, "ingest"),
        "sources": sources,
        "counts": {
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "clusters": conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0],
            "signals": conn.execute("SELECT COUNT(*) FROM signals WHERE status='published'").fetchone()[0],
            "snapshots": conn.execute("SELECT COUNT(*) FROM edition_snapshots").fetchone()[0],
        },
    }


def recent_leads(conn: sqlite3.Connection, days: int, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT d.id, d.url, d.title, d.excerpt, d.source_type, d.published_at, d.event_date, d.first_seen_at, "
        "d.retrieved_at, d.cluster_id, s.name AS source_name, s.kind AS source_kind, "
        "(SELECT COUNT(*) FROM documents d2 WHERE d2.cluster_id=d.cluster_id) AS cluster_size, "
        "(SELECT GROUP_CONCAT(signal_id) FROM signal_matches m WHERE m.document_id=d.id) AS matched_signals, "
        "(SELECT json_group_array(json_object('signal', m.signal_id, 'terms', json(m.terms))) FROM signal_matches m "
        "WHERE m.document_id=d.id) AS matches, "
        "(SELECT COUNT(*) FROM document_revisions r WHERE r.document_id=d.id) AS revisions "
        "FROM documents d LEFT JOIN sources s ON s.id=d.source_id "
        "WHERE d.origin='ingested' AND d.first_seen_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?) "
        "ORDER BY COALESCE(d.published_at, d.first_seen_at) DESC LIMIT ?", (f"-{days} days", limit)).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        row["matches"] = loads(row["matches"]) or []
        out.append(row)
    return out
