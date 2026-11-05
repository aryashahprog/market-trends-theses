from __future__ import annotations

import hmac
import logging
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .adapters.base import Adapter
from .config import Settings, get_settings
from .db import connect
from .export import edition_markdown
from .pipeline import get_series, get_status, latest_snapshot, list_editions, lock_held, run_pipeline
from .seed import seed_if_empty

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("signal_atlas.app")
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


def create_app(settings: Settings | None = None,
               adapters_factory: Callable[[Settings], Sequence[Adapter]] | None = None) -> FastAPI:
    cfg = settings or get_settings()

    def db() -> sqlite3.Connection:
        return connect(cfg.db_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        c = db()
        seed_if_empty(c)
        c.close()
        sched = None
        if cfg.run_scheduler_in_web:
            from .worker import build_scheduler
            sched = build_scheduler(cfg, background=True)
            sched.start()
        yield
        if sched:
            sched.shutdown(wait=False)

    app = FastAPI(title="Signal Atlas", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def rate_count(c: sqlite3.Connection, key: str, window_s: float) -> int:
        now = time.time()
        c.execute("DELETE FROM rate_events WHERE at < ?", (now - 86400,))
        return int(c.execute("SELECT COUNT(*) FROM rate_events WHERE key=? AND at>=?",
                             (key, now - window_s)).fetchone()[0])

    def rate_hit(c: sqlite3.Connection, key: str) -> None:
        c.execute("INSERT INTO rate_events(key, at) VALUES (?,?)", (key, time.time()))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        c = db()
        try:
            return get_status(c, cfg)
        finally:
            c.close()

    @app.get("/api/editions")
    def editions() -> list[dict[str, Any]]:
        c = db()
        try:
            return list_editions(c)
        finally:
            c.close()

    @app.get("/api/edition")
    def edition(date: str | None = None) -> dict[str, Any]:
        c = db()
        try:
            snap = latest_snapshot(c, date)
        finally:
            c.close()
        if not snap:
            raise HTTPException(404, "No edition for that date")
        return snap

    @app.get("/api/leads")
    def leads(days: int = 3, limit: int = 80) -> list[dict[str, Any]]:
        days, limit = max(1, min(days, 30)), max(1, min(limit, 200))
        c = db()
        try:
            rows = c.execute(
                "SELECT d.id, d.url, d.title, d.excerpt, d.source_type, d.published_at, d.event_date, d.first_seen_at, "
                "d.retrieved_at, d.cluster_id, s.name AS source_name, s.kind AS source_kind, "
                "(SELECT COUNT(*) FROM documents d2 WHERE d2.cluster_id=d.cluster_id) AS cluster_size, "
                "(SELECT GROUP_CONCAT(signal_id) FROM signal_matches m WHERE m.document_id=d.id) AS matched_signals, "
                "(SELECT COUNT(*) FROM document_revisions r WHERE r.document_id=d.id) AS revisions "
                "FROM documents d LEFT JOIN sources s ON s.id=d.source_id "
                "WHERE d.origin='ingested' AND d.first_seen_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?) "
                "ORDER BY COALESCE(d.published_at, d.first_seen_at) DESC LIMIT ?", (f"-{days} days", limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            c.close()

    @app.get("/api/series/{sid:path}")
    def series(sid: str) -> dict[str, Any]:
        c = db()
        try:
            s = get_series(c, sid)
        finally:
            c.close()
        if not s:
            raise HTTPException(404, "Series not available (not yet ingested from its source)")
        return s

    @app.get("/api/export/{date}.md", response_class=PlainTextResponse)
    def export(date: str) -> PlainTextResponse:
        c = db()
        try:
            snap = latest_snapshot(c, date)
        finally:
            c.close()
        if not snap:
            raise HTTPException(404, "No edition for that date")
        return PlainTextResponse(edition_markdown(snap), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="signal-atlas-{date}.md"'})

    def _manual_run() -> None:
        c = db()
        try:
            adapters = adapters_factory(cfg) if adapters_factory else None
            run_pipeline(c, cfg, "manual", adapters=adapters)
        except Exception:
            log.exception("manual refresh failed")
        finally:
            c.close()

    @app.post("/api/admin/refresh", status_code=202)
    def refresh(request: Request) -> JSONResponse:
        if not cfg.admin_token:
            raise HTTPException(503, "Manual refresh is disabled: no admin token is configured on the server.")
        ip = request.client.host if request.client else "unknown"
        c = db()
        try:
            if rate_count(c, f"authfail:{ip}", 900) >= 5:
                raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.",
                                    headers={"Retry-After": "900"})
            auth = request.headers.get("authorization", "")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if not hmac.compare_digest(token.encode(), cfg.admin_token.encode()):
                rate_hit(c, f"authfail:{ip}")
                raise HTTPException(401, "Invalid admin token.", headers={"WWW-Authenticate": "Bearer"})
            cooldown = cfg.manual_refresh_min_interval_s
            if rate_count(c, "refresh", cooldown) >= 1:
                raise HTTPException(429, f"Manual refresh is limited to one per {cooldown // 60} minutes.",
                                    headers={"Retry-After": str(cooldown)})
            if lock_held(c, "ingest"):
                raise HTTPException(409, "An ingestion run is already in progress.")
            rate_hit(c, "refresh")
        finally:
            c.close()
        threading.Thread(target=_manual_run, name="manual-refresh", daemon=True).start()
        return JSONResponse({"status": "started"}, status_code=202)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
