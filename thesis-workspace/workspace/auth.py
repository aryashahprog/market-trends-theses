import hashlib
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import demo
from .data import db, person

bp = Blueprint("auth", __name__)
TOKEN_TTL = 15 * 60


def login_required(view):
    @wraps(view)
    def protected(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.sign_in"))
        return view(*args, **kwargs)

    return protected


def sign_user_in(person_id: int, demo_space: str | None = None) -> None:
    revoke_session()
    token = secrets.token_urlsafe(32)
    ts = int(time.time())
    db().execute("DELETE FROM sessions WHERE expires <= ?", (ts,))
    db().execute(
        "INSERT INTO sessions VALUES (?,?,?)",
        (
            token_hash(token),
            person_id,
            ts + int(current_app.permanent_session_lifetime.total_seconds()),
        ),
    )
    db().commit()
    session.permanent = True
    session["auth_token"] = token
    if demo_space:
        session["demo_space"] = demo_space


def revoke_session() -> None:
    if token := session.get("auth_token"):
        db().execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
    session.clear()


def mail_ready() -> bool:
    config = current_app.config
    return bool(
        config["SMTP_HOST"]
        and config["SMTP_FROM"]
        and config["TEAM_EMAILS"]
        and config["BASE_URL"]
        and (
            (config["BASE_URL"].startswith("https://") and config["SESSION_COOKIE_SECURE"])
            or config["TESTING"]
        )
    )


def deliver(email: str, token: str) -> None:
    config = current_app.config
    message = EmailMessage()
    message["From"] = config["SMTP_FROM"]
    message["To"] = email
    message["Subject"] = "Sign in to Thesis Workspace"
    link = config["BASE_URL"] + url_for("auth.redeem", token=token)
    message.set_content(f"Open this single-use link within 15 minutes:\n\n{link}\n")
    context = ssl.create_default_context()
    if config["SMTP_PORT"] == 465:
        with smtplib.SMTP_SSL(config["SMTP_HOST"], 465, timeout=10, context=context) as smtp:
            send_message(smtp, message)
    else:
        with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PORT"], timeout=10) as smtp:
            smtp.starttls(context=context)
            send_message(smtp, message)


def send_message(smtp: smtplib.SMTP, message: EmailMessage) -> None:
    config = current_app.config
    if config["SMTP_USER"]:
        smtp.login(config["SMTP_USER"], config["SMTP_PASSWORD"] or "")
    smtp.send_message(message)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@bp.get("/sign-in")
def sign_in():
    if g.user is not None:
        return redirect(url_for("views.team"))
    return render_template("sign_in.html", ready=mail_ready())


@bp.post("/sign-in")
def request_login():
    if not mail_ready():
        abort(503, "Work email sign-in is not configured. Try the fictional demo.")
    email = request.form.get("email", "").strip().lower()
    if email in current_app.config["TEAM_EMAILS"]:
        ts = int(time.time())
        db().execute("DELETE FROM login_tokens WHERE expires < ?", (ts,))
        recent = (
            db()
            .execute(
                "SELECT COUNT(*) FROM login_tokens WHERE email = ? AND created > ?",
                (email, ts - 60),
            )
            .fetchone()[0]
        )
        recent_total = (
            db()
            .execute(
                "SELECT COUNT(*) FROM login_tokens WHERE created > ?",
                (ts - 60,),
            )
            .fetchone()[0]
        )
        if not recent and recent_total < 30:
            token = secrets.token_urlsafe(32)
            db().execute(
                "INSERT INTO login_tokens VALUES (?,?,?,?)",
                (
                    token_hash(token),
                    email,
                    ts,
                    ts + TOKEN_TTL,
                ),
            )
            db().commit()
            try:
                deliver(email, token)
            except (OSError, smtplib.SMTPException):
                current_app.logger.warning("Email delivery failed")
                abort(503, "Could not send sign-in email. Try again later.")
    return render_template("sign_in.html", ready=True, sent=True)


@bp.route("/sign-in/confirm", methods=["GET", "POST"])
def redeem():
    token = (request.args if request.method == "GET" else request.form).get("token", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{43}", token):
        abort(400, "This sign-in link is invalid or expired.")
    digest = token_hash(token)
    record = (
        db()
        .execute(
            "SELECT email FROM login_tokens WHERE token_hash = ? AND expires >= ?",
            (digest, int(time.time())),
        )
        .fetchone()
    )
    if record is None or record["email"] not in current_app.config["TEAM_EMAILS"]:
        abort(400, "This sign-in link is invalid or expired.")
    if request.method == "GET":
        return render_template("sign_in.html", ready=True, token=token)
    email = record["email"]
    name = re.sub(r"[._\-+]+", " ", email.split("@", 1)[0]).title()
    person_id = person("team", email, name)
    db().execute("UPDATE login_tokens SET expires = 0 WHERE token_hash = ?", (digest,))
    sign_user_in(person_id)
    return redirect(url_for("views.team"))


@bp.post("/demo")
def start_demo():
    if not current_app.config["DEMO_ENABLED"]:
        abort(404)
    if g.user is not None:
        return redirect(url_for("views.team"))
    space = "demo:" + secrets.token_urlsafe(24)
    person_id = demo.seed(space)
    sign_user_in(person_id, space)
    return redirect(url_for("views.team"))


@bp.post("/demo/switch")
@login_required
def switch_demo():
    space = session.get("demo_space")
    choice = request.form.get("person", "")
    if space is None or g.user["space"] != space or choice not in demo.PEOPLE:
        abort(404)
    email, name = demo.PEOPLE[choice]
    person_id = person(space, email, name)
    sign_user_in(person_id, space)
    return redirect(url_for("views.team"))


@bp.post("/sign-out")
@login_required
def sign_out():
    revoke_session()
    db().commit()
    return redirect(url_for("auth.sign_in"))
