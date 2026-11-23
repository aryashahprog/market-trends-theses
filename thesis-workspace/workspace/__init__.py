import hmac
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path

from flask import Flask, abort, g, render_template, request, session
from werkzeug.exceptions import HTTPException

from . import auth, views
from .data import connect
from .ingest import MAX_FILE


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get(
            "THESIS_WORKSPACE_DATABASE", str(Path(app.instance_path) / "workspace.sqlite")
        ),
        SECRET_KEY=os.environ.get("THESIS_WORKSPACE_SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("THESIS_WORKSPACE_SECURE_COOKIE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        MAX_CONTENT_LENGTH=MAX_FILE + 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=300_000,
        MAX_FORM_PARTS=30,
        DEMO_ENABLED=os.environ.get("THESIS_WORKSPACE_DEMO", "1") == "1",
        TEAM_EMAILS=set(
            os.environ.get("THESIS_WORKSPACE_TEAM_EMAILS", "").lower().replace(",", " ").split()
        ),
        BASE_URL=os.environ.get("THESIS_WORKSPACE_BASE_URL", "").rstrip("/"),
        SMTP_HOST=os.environ.get("THESIS_WORKSPACE_SMTP_HOST"),
        SMTP_PORT=int(os.environ.get("THESIS_WORKSPACE_SMTP_PORT", "587")),
        SMTP_USER=os.environ.get("THESIS_WORKSPACE_SMTP_USER"),
        SMTP_PASSWORD=os.environ.get("THESIS_WORKSPACE_SMTP_PASSWORD"),
        SMTP_FROM=os.environ.get("THESIS_WORKSPACE_SMTP_FROM"),
        OPENAI_API_KEY=os.environ.get("THESIS_WORKSPACE_OPENAI_API_KEY"),
        OPENAI_MODEL=os.environ.get("THESIS_WORKSPACE_OPENAI_MODEL", "gpt-4.1-mini"),
    )
    if config:
        app.config.update(config)
    database = Path(app.config["DATABASE"])
    database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        key_path = database.with_suffix(".session-key")
        try:
            with key_path.open("r", encoding="ascii") as key:
                app.config["SECRET_KEY"] = key.read().strip()
        except FileNotFoundError:
            secret = secrets.token_hex(32)
            try:
                key_fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                secret = key_path.read_text(encoding="ascii").strip()
            else:
                with os.fdopen(key_fd, "w") as secret_file:
                    secret_file.write(secret)
            app.config["SECRET_KEY"] = secret
    with app.app_context():
        conn = connect(str(database))
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            schema = Path(__file__).with_name("schema.sql").read_text()
            conn.execute("BEGIN IMMEDIATE")
            if any(
                row["name"] == "thesis_id" and row["notnull"]
                for row in conn.execute("PRAGMA table_info(sources)")
            ):
                conn.execute("ALTER TABLE sources RENAME TO attached_sources")
                conn.execute("DROP INDEX IF EXISTS sources_by_thesis")
            for statement in schema.split(";"):
                if statement.strip():
                    conn.execute(statement)
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'attached_sources'"
            ).fetchone():
                columns = (
                    "id, thesis_id, added_by, added, title, author, visibility, "
                    "kind, url, filename, file_bytes, passage_data"
                )
                conn.execute(
                    f"INSERT INTO sources ({columns}) SELECT {columns} FROM attached_sources"
                )
                conn.execute("DROP TABLE attached_sources")
            if not any(
                row["name"] == "deleted" for row in conn.execute("PRAGMA table_info(sources)")
            ):
                conn.execute("ALTER TABLE sources ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
            if not any(
                row["name"] == "token" for row in conn.execute("PRAGMA table_info(versions)")
            ):
                conn.execute("ALTER TABLE versions ADD COLUMN token TEXT")
                conn.execute("UPDATE versions SET token = lower(hex(randomblob(16)))")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS versions_by_token ON versions(token)")
            conn.commit()
        finally:
            conn.close()

    @app.before_request
    def load_user() -> None:
        if request.endpoint == "static":
            return
        if request.method == "POST":
            token = session.get("csrf", "")
            if not token or not hmac.compare_digest(
                token.encode(), request.form.get("csrf", "").encode()
            ):
                abort(400, "This form expired. Reload the page and try again.")
        g.db = connect(app.config["DATABASE"])
        write = request.method == "POST" and request.endpoint not in {
            "views.ask",
            "views.add_research",
        }
        g.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        g.user = None
        if session.get("auth_token"):
            member = g.db.execute(
                """SELECT p.* FROM sessions s JOIN people p ON p.id = s.person_id
                WHERE s.token_hash = ? AND s.expires > ?""",
                (auth.token_hash(session["auth_token"]), int(time.time())),
            ).fetchone()
            if member is not None and (
                (member["space"] == "team" and member["email"] in app.config["TEAM_EMAILS"])
                or (app.config["DEMO_ENABLED"] and member["space"] == session.get("demo_space"))
            ):
                g.user = member

    @app.context_processor
    def shared_context() -> dict:
        def csrf_token() -> str:
            if "csrf" not in session:
                session["csrf"] = secrets.token_urlsafe(32)
            return str(session["csrf"])

        def demo_profiles() -> list[tuple[str, str, str]]:
            rows = g.db.execute(
                "SELECT email, name FROM people WHERE space = ?", (g.user["space"],)
            )
            names = {row["email"]: row["name"] for row in rows}
            return [
                (key, email, names.get(email, name))
                for key, (email, name) in auth.demo.PEOPLE.items()
            ]

        return {"csrf_token": csrf_token, "demo_profiles": demo_profiles}

    @app.teardown_appcontext
    def close_db(_exc: BaseException | None) -> None:
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.after_request
    def headers(response):
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
            "; frame-ancestors 'self' https://app.devin.ai"
        )
        return response

    @app.errorhandler(HTTPException)
    def error(exc: HTTPException):
        return render_template("error.html", error=exc), exc.code

    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    return app
