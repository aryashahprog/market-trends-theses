# Thesis Workspace

A private workspace for owner-authored investment theses, supporting research, and cited cross-thesis queries. Flask renders the UI; SQLite stores all workspace data, including original uploads.

This app runs separately from Signal Atlas. It has its own dependencies, database, and server; it is not part of the GitHub Pages publishing pipeline.

## Run locally

Requires Python 3.10+.

```sh
cd thesis-workspace
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/flask --app workspace run
```

Open the development address printed by Flask and choose **Open fictional demo**. Each demo is a separate writable workspace with a fixed roster of fictional people and a profile switcher for trying permissions. Switching personas intentionally changes what you can see inside that demo; it does not grant access to real accounts or other demos. Exiting a demo ends access to that instance.

## Deploy for real team use

Serve over HTTPS behind a proxy, on one machine with a persistent volume and restrictive filesystem permissions. Run:

```sh
.venv/bin/gunicorn --preload --workers 2 --threads 2 --bind 0.0.0.0:8080 workspace.wsgi:app
```

Set environment variables before starting (see `.env.example`):

| Variable | Purpose |
| --- | --- |
| `THESIS_WORKSPACE_DATABASE` | Absolute path on the persistent volume to the SQLite database. Files are stored in the database, not served from a public directory. |
| `THESIS_WORKSPACE_SECRET_KEY` | Strong random value for signed sessions. If unset, the app creates a persistent key alongside the DB (keep it private, and use preload). |
| `THESIS_WORKSPACE_BASE_URL` | Public HTTPS origin (no subpath), used to build sign-in links. |
| `THESIS_WORKSPACE_SECURE_COOKIE` | Set to `1` for HTTPS. Leave unset only for local HTTP development. |
| `THESIS_WORKSPACE_TEAM_EMAILS` | Explicit allowlist of work emails, separated by commas or spaces; no open registration. |
| `THESIS_WORKSPACE_SMTP_HOST`, `THESIS_WORKSPACE_SMTP_PORT`, `THESIS_WORKSPACE_SMTP_FROM` | SMTP host, port and verified sender. Uses STARTTLS (default 587) or implicit TLS (465). |
| `THESIS_WORKSPACE_SMTP_USER`, `THESIS_WORKSPACE_SMTP_PASSWORD` | SMTP account credentials if your provider requires authentication. |
| `THESIS_WORKSPACE_DEMO` | Set to `0` to disable the isolated fictional demo. Defaults to enabled. |
| `THESIS_WORKSPACE_OPENAI_API_KEY`, `THESIS_WORKSPACE_OPENAI_MODEL` | Optional OpenAI API credential and model (default `gpt-4.1-mini`). Omit to keep all retrieval local. |

The app does not source an environment file automatically; export these settings or use your host’s secret manager. Do not commit credentials. Sign-in links are single-use and expire in 15 minutes, and the work-email allowlist is rechecked on every app request. Each sign-in expires after 24 hours and is revoked server-side on sign-out. After sign-in users can edit their display name, which must be unique within their workspace. Without SMTP and an allowlist the real workspace is unavailable, and the UI says so; the demo still works.

For persistent hosting, back up the SQLite database using SQLite's online backup API (or stop the server before making a file copy). Do not copy just the live DB file while it is using WAL. The supplied Devin App deployment is for trying the fictional demo, not storing sensitive firm information; its availability depends on the managing session. Keep its app database outside the checkout when redeploying.

## How research and Ask work

- The owner writes and edits the argument; edits append immutable revisions. Publishing a thesis does not publish earlier draft revisions or draft attachments. Only the source submitter can share a draft attachment, and its parent thesis must be shared.
- An edit based on an older revision is rejected rather than overwriting newer work. Version pages compare against the previous version visible to that reader. The owner can restore a saved revision as a new one without removing history; restoring never publishes a draft.
- Add research can save a private note without a thesis or a title. The submitter can attach it to a thesis later and choose Team visibility when the destination is shared.
- Supporting material is attributed separately to its author, submitter and thesis owner. On shared theses, visible evidence and discussion identify contributors. Related theses are linked via shared topics.
- Paste text, upload an original PDF/DOCX/UTF-8 TXT, or save an HTTP(S) reference. PDFs and DOCX files are extracted in-process with limits; scanned PDFs are not OCR’d and may have no searchable passages. URLs (including Google Drive and Granola) are **reference only**: no fetching, crawlers, or account integrations.
- A duplicate URL on the same thesis is flagged if you can already see the existing reference. The submitter can correct the title, author or reference URL, or delete the source. Pasted and extracted passages cannot be edited in place; replacing the material with a new source preserves citation integrity. Citations to a deleted source stop resolving.
- Ask retrieves only team theses and the current user’s own accessible drafts. It ranks accessible owner arguments, questions, competing views and extracted passages by keyword relevance. It does not retrieve comments, unimported links, or revision history. Citations link to the immutable thesis revision or exact source passage.
- Ask result links are private to the current sign-in. They work for one hour with citation access checked again on return; questions are not placed in URLs. Signing out removes that session’s saved results.
- Passage search is the credential-free mode and quotes original passages rather than guessing at a synthesis. When AI is configured, a user can explicitly opt into sending the question and selected excerpts (potentially their own drafts) to OpenAI for that request. Confirm your firm's data-handling policy before enabling it; the app validates citation IDs but does not certify that every model claim is supported. Model errors fall back to local passage search. Neither mode writes to a thesis.

## Checks

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy workspace
.venv/bin/pytest -q
```
