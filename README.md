# Market Trends → Theses

A dated, evidence-backed feed of emerging market signals. Each signal is a working investment thesis with what changed,
why now, the market indication (an economic implication, never a buy/sell call), the startup opportunity, the corporate
buyer and use case, evidence and counterevidence with full provenance, a confidence rationale, the next validation step
and a falsifier.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export SIGNAL_ATLAS_DATA_DIR=$PWD/data
.venv/bin/python -m signal_atlas.cli seed          # verified first edition
.venv/bin/python -m signal_atlas.cli ingest        # one ingestion pass now
.venv/bin/uvicorn signal_atlas.app:create_app --factory --port 8080   # web + API
.venv/bin/python -m signal_atlas.worker           # scheduler (separate process)
```

`cli status` prints pipeline health; `cli schedule` prints the next six refresh times.

## Scheduling

The worker (`signal_atlas.worker`) is an APScheduler process with `CronTrigger(hour="8,16", minute=0,
timezone="America/New_York")`, so runs follow DST automatically. It runs independently of any browser, writes a
heartbeat every minute, takes a database lease so runs never overlap, and runs a catch-up pass at startup if the last
scheduled slot was missed. The browser only polls status for display; it never triggers ingestion on a timer.
Setting `SIGNAL_ATLAS_SCHEDULER_IN_WEB=1` embeds the scheduler in the web process for single-process hosts.

## Configuration (server-side environment only)

| Variable | Purpose |
| --- | --- |
| `SIGNAL_ATLAS_DATA_DIR` / `SIGNAL_ATLAS_DB` | SQLite location (WAL mode) |
| `SIGNAL_ATLAS_ADMIN_TOKEN` | Enables `POST /api/admin/refresh` (Bearer, ≥24 chars). Unset = disabled |
| `SEC_USER_AGENT` | Required for SEC EDGAR: `"Name contact@example.org"` per SEC fair-access policy. Unset = SEC source reports failed |
| `SIGNAL_ATLAS_USER_AGENT` | User-Agent for other public sources |
| `SIGNAL_ATLAS_REFRESH_COOLDOWN_S` | Minimum seconds between manual refreshes (default 600) |
| `SIGNAL_ATLAS_STALE_GRACE_MIN` | Minutes after a slot before data is flagged stale (default 90) |

Manual refresh is rate-limited and failed-auth attempts lock out after five tries per 15 minutes.

## Sources and access

| Source | Method | Role |
| --- | --- | --- |
| Milk Road | public sitemap + page metadata | discovery (reported) |
| MarketWatch | public Dow Jones RSS (HTML is access-restricted and is not bypassed) | discovery (reported) |
| SEC EDGAR | full-text search API with declared User-Agent | primary |
| Price of Compute | public JSON API, attributed | pricing dataset / sourced charts |
| Silicon Data | public index page values | corroborating pricing dataset |
| Ramp AI Index | public page headline figures | adoption dataset |

All retrieval honours robots.txt, uses a persistent HTTP cache with ETag/Last-Modified, per-host rate limits and a size
cap. Pages returning 401/402/403 are recorded as restricted and never bypassed. Only titles, metadata and short
sanitized excerpts are stored; full articles are never copied. Scraped text is treated as untrusted and rendered as text.

## Data model and integrity

- Canonical-URL deduplication (scheme/host/tracking-parameter normalisation); every content change saves a revision.
- Provenance on every document: source type, event date, publication date, first-seen time, retrieved time.
- Evidence is typed `primary`, `corroborated` or `reported`; narrative fields are labelled analyst inference.
- A signal is publishable only with at least one primary or corroborated item and at least one challenging item.
- Related stories are clustered across sources; ingested items that match a signal appear as *unreviewed mentions*
  and never become evidence automatically.
- Each source runs in its own transaction: a failing source is recorded and rolled back while prior good data and
  other sources are preserved. Daily edition snapshots are written after each non-failed run.
- Ranking is a transparent weighted sum (novelty 20%, evidence 35%, relevance 20%, impact 25%) used only to order the
  feed. It is not a probability, forecast or recommendation.
- Charts render only from retrieved series; nothing is drawn without data.

## Deploy

`deploy/` contains a Dockerfile, a compose file running `web` and `worker` against a shared volume, and systemd units.
Any host with a persistent disk works. A preview server without the worker process is *not* persistent ingestion.

## Checks

```bash
.venv/bin/pytest -q && .venv/bin/ruff check signal_atlas tests && .venv/bin/mypy
```

### Static hosting with scheduled GitHub Actions

`.github/workflows/publish.yml` runs ingestion on GitHub's runners at 08:00 and 16:00 America/New_York (UTC cron
entries for both EDT and EST, gated by `cli due` so each slot runs once), keeps the SQLite database on a `data`
branch, and publishes a read-only static build (`cli export`) to GitHub Pages. In static mode manual refresh is the
workflow's "Run workflow" button; set the optional `SEC_USER_AGENT` repository secret to enable SEC EDGAR.
