import io
import json
import secrets
import sqlite3
import time
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from . import ask as research
from .auth import login_required, token_hash
from .data import (
    STATUSES,
    THESIS_FIELDS,
    db,
    name_taken,
    now,
    save_thesis,
    source_or_404,
    sources,
    theses,
    thesis_or_404,
    viewer,
)
from .ingest import MAX_TEXT, file_content, passages, safe_link

bp = Blueprint("views", __name__)
REVISION_FIELDS = dict(
    zip(
        THESIS_FIELDS,
        (
            "Title",
            "Current argument",
            "Open questions",
            "Competing views",
            "Topics",
            "Status",
            "Visibility",
            "Last reviewed",
        ),
    )
)
EDIT_CONFLICT = (
    "Someone saved a newer revision after this page opened. Your changes were not saved."
)


def today() -> date:
    return datetime.now(timezone.utc).date()


def field(name: str, limit: int, required: bool = False) -> str:
    value = request.form.get(name, "").strip()
    if required and not value:
        raise ValueError(f"{name.replace('_', ' ').capitalize()} is required.")
    if len(value) > limit:
        raise ValueError(f"{name.replace('_', ' ').capitalize()} exceeds {limit:,} characters.")
    return value


def visibility(name: str = "visibility") -> str:
    value = request.form.get(name, "draft")
    if value not in {"draft", "team"}:
        raise ValueError("Choose draft or team visibility.")
    return value


def duplicate_reference(url: str, thesis_id: int | None, excluding: int = 0) -> sqlite3.Row | None:
    if not url:
        return None
    candidates = sources(
        " AND s.thesis_id IS ? AND s.kind = 'link' AND s.url = ? AND s.id != ?",
        (thesis_id, url, excluding),
    )
    return candidates[0] if candidates else None


def topic_list(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def thesis_values() -> dict[str, str]:
    values = {
        "title": field("title", 160, True),
        "argument": field("argument", 12000),
        "questions": field("questions", 6000),
        "competing": field("competing", 6000),
        "topics": ", ".join(topic_list(field("topics", 200))),
        "status": field("status", 12),
        "visibility": visibility(),
        "reviewed": field("reviewed", 10),
    }
    if values["status"] not in STATUSES:
        raise ValueError("Choose a thesis status.")
    if values["reviewed"]:
        try:
            reviewed = date.fromisoformat(values["reviewed"])
        except ValueError as exc:
            raise ValueError("Enter a valid review date.") from exc
        if reviewed > today():
            raise ValueError("Last reviewed cannot be in the future.")
        values["reviewed"] = reviewed.isoformat()
    return values


@bp.app_template_filter("topics")
def display_topics(value: str) -> list[str]:
    return topic_list(value)


@bp.app_template_filter("date")
def display_date(value: str) -> str:
    return date.fromisoformat(value[:10]).strftime("%b %d, %Y") if value else "Not reviewed"


@bp.app_template_filter("timestamp")
def display_timestamp(value: str) -> str:
    return (
        datetime.fromisoformat(value).astimezone(timezone.utc).strftime("%b %d, %Y at %H:%M:%S UTC")
    )


@bp.get("/")
@login_required
def team():
    shared = [item for item in theses() if item["visibility"] == "team"]
    q = request.args.get("q", "").strip()
    owner = request.args.get("owner", "")
    status = request.args.get("status", "")
    topic = request.args.get("topic", "")
    filtered = [
        t
        for t in shared
        if (not owner or str(t["owner_id"]) == owner)
        and (not status or t["status"] == status)
        and (not topic or topic in topic_list(t["topics"]))
        and (
            not q
            or all(
                term
                in " ".join(
                    t[k]
                    for k in (
                        "title",
                        "owner",
                        "topics",
                        "argument",
                        "questions",
                        "competing",
                        "status",
                    )
                ).casefold()
                for term in q.casefold().split()
            )
        )
    ]
    owners = sorted({(str(t["owner_id"]), t["owner"]) for t in shared}, key=lambda x: x[1])
    topics = sorted({label for t in shared for label in topic_list(t["topics"])}, key=str.casefold)
    return render_template(
        "team.html",
        items=filtered,
        owners=owners,
        topics=topics,
        total=len(shared),
        statuses=STATUSES,
        q=q,
        owner=owner,
        status=status,
        topic=topic,
    )


@bp.get("/my-research")
@login_required
def mine():
    _, person = viewer()
    items = [item for item in theses() if item["owner_id"] == person]
    return render_template(
        "mine.html",
        items=items,
        attachments=sources(" AND s.added_by = ?", (person,)),
        drafts=sum(item["visibility"] == "draft" for item in items),
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        try:
            name = " ".join(field("name", 80, True).split())
            if any(unicodedata.category(char).startswith("C") for char in name):
                raise ValueError("Enter a name without hidden or control characters.")
            space, person_id = viewer()
            if name_taken(space, name, excluding=person_id):
                raise ValueError("That display name is already taken in this workspace.")
        except ValueError as exc:
            return render_template("profile.html", problem=str(exc)), 400
        db().execute("UPDATE people SET name = ? WHERE id = ?", (name, g.user["id"]))
        db().commit()
        return redirect(url_for("views.profile"))
    return render_template("profile.html")


@bp.get("/thesis/<int:thesis_id>")
@login_required
def thesis(thesis_id: int):
    item = thesis_or_404(thesis_id)
    own = item["owner_id"] == g.user["id"]
    attached = sources(" AND s.thesis_id = ?", (thesis_id,))
    comments = (
        db()
        .execute(
            """SELECT c.*, p.name FROM comments c JOIN people p ON c.person_id = p.id
        WHERE c.thesis_id = ? ORDER BY c.id ASC""",
            (thesis_id,),
        )
        .fetchall()
    )
    history = (
        db()
        .execute(
            """SELECT * FROM versions WHERE thesis_id = ? AND (? OR visibility = 'team')
        ORDER BY revision DESC""",
            (thesis_id, own),
        )
        .fetchall()
    )
    contributors = {(s["added_by"], s["added_name"]) for s in attached}
    contributors.update((c["person_id"], c["name"]) for c in comments)
    contributors = {name for person, name in contributors if person != item["owner_id"]}
    topic_keys = set(map(str.casefold, topic_list(item["topics"])))
    related = [
        (t, len(topic_keys & set(map(str.casefold, topic_list(t["topics"])))))
        for t in theses()
        if t["visibility"] == "team" and t["id"] != thesis_id
    ]
    return render_template(
        "thesis.html",
        item=item,
        own=own,
        attached=attached,
        comments=comments,
        history=[(version, json.loads(version["snapshot"])) for version in history],
        contributors=sorted(contributors, key=str.casefold),
        related=[t for t, score in sorted(related, key=lambda pair: -pair[1]) if score][:3],
        passages=passages,
    )


def edit_form(item: sqlite3.Row | None = None):
    context = {"item": item, "statuses": STATUSES, "today": today().isoformat()}
    if request.method == "POST":
        if item is not None and request.form.get("base_version") != item["version_token"]:
            return render_template(
                "edit.html", **context, values=request.form, conflict=True, problem=EDIT_CONFLICT
            ), 409
        try:
            values = thesis_values()
        except ValueError as exc:
            return render_template(
                "edit.html", **context, values=request.form, problem=str(exc)
            ), 400
        thesis_id = save_thesis(values, *viewer(), thesis_id=item["id"] if item else None)
        db().commit()
        return redirect(url_for("views.thesis", thesis_id=thesis_id))
    return render_template("edit.html", **context, values=dict(item) if item else {})


@bp.get("/thesis/<int:thesis_id>/version/<token>")
@login_required
def version(thesis_id: int, token: str):
    item = thesis_or_404(thesis_id)
    own = item["owner_id"] == g.user["id"]
    record = visible_version(thesis_id, token, own)
    older = (
        db()
        .execute(
            """SELECT snapshot FROM versions WHERE thesis_id = ? AND revision < ?
           AND (? OR visibility = 'team') ORDER BY revision DESC LIMIT 1""",
            (thesis_id, record["revision"], own),
        )
        .fetchone()
    )
    snapshot = json.loads(record["snapshot"])
    previous = json.loads(older["snapshot"]) if older else {}
    changes = [
        (label, previous[key], snapshot[key])
        for key, label in REVISION_FIELDS.items()
        if key in previous and previous[key] != snapshot[key]
    ]
    return render_template(
        "version.html",
        item=item,
        own=own,
        record=record,
        snapshot=snapshot,
        passages=passages,
        older=older is not None,
        changes=changes,
    )


def visible_version(thesis_id: int, token: str, own: bool) -> sqlite3.Row:
    record = (
        db()
        .execute(
            """SELECT * FROM versions WHERE thesis_id = ? AND token = ?
        AND (? OR visibility = 'team')""",
            (thesis_id, token, own),
        )
        .fetchone()
    )
    if record is None:
        abort(404)
    return record


@bp.post("/thesis/<int:thesis_id>/version/<token>/restore")
@login_required
def restore_version(thesis_id: int, token: str):
    item = thesis_or_404(thesis_id)
    if item["owner_id"] != g.user["id"]:
        abort(403, "Only the thesis owner can restore a version.")
    if request.form.get("base_version") != item["version_token"]:
        abort(409, EDIT_CONFLICT)
    record = visible_version(thesis_id, token, True)
    values = json.loads(record["snapshot"])
    if item["visibility"] == "draft" or record["visibility"] == "draft":
        values["visibility"] = "draft"
    if values["reviewed"] and date.fromisoformat(values["reviewed"]) > today():
        values["reviewed"] = ""
    save_thesis(values, *viewer(), thesis_id=thesis_id)
    db().commit()
    return redirect(url_for("views.thesis", thesis_id=thesis_id), code=303)


@bp.route("/thesis/new", methods=["GET", "POST"])
@login_required
def new():
    return edit_form()


@bp.route("/thesis/<int:thesis_id>/edit", methods=["GET", "POST"])
@login_required
def edit(thesis_id: int):
    item = thesis_or_404(thesis_id)
    if item["owner_id"] != g.user["id"]:
        abort(403, "Only the thesis owner can edit the argument.")
    return edit_form(item)


@bp.post("/thesis/<int:thesis_id>/discussion")
@login_required
def comment(thesis_id: int):
    item = thesis_or_404(thesis_id)
    if item["visibility"] != "team":
        abort(403, "Discussion is available on team theses only.")
    try:
        body = field("comment", 3500, True)
    except ValueError as exc:
        abort(400, str(exc))
    db().execute(
        "INSERT INTO comments (thesis_id, person_id, body, created) VALUES (?,?,?,?)",
        (thesis_id, g.user["id"], body, now()),
    )
    db().commit()
    return redirect(url_for("views.thesis", thesis_id=thesis_id) + "#discussion")


@bp.route("/research/add", methods=["GET", "POST"])
@login_required
def add_research():
    if request.method == "POST":
        db().rollback()
        duplicate = None
        try:
            selection = field("thesis", 20)
            title = field("source_title", 160)
            author = field("source_author", 160)
            scope = visibility("source_visibility")
            kind = request.form.get("kind", "text")
            attachment_url, filename, blob, extracted = "", "", None, "[]"
            upload = request.files.get("file")
            missing = []
            if kind == "text" and not request.form.get("text", "").strip():
                missing.append("Paste research text.")
            if kind == "link" and not request.form.get("url", "").strip():
                missing.append("Enter a source URL.")
            if kind == "file" and (upload is None or not upload.filename):
                missing.append("Choose a file.")
            if selection == "new" and not request.form.get("new_title", "").strip():
                missing.append("Enter a title for the new thesis.")
            if not selection and scope == "team":
                missing.append("Choose a team thesis to share this evidence.")
            if missing:
                raise ValueError(" ".join(missing))
            if kind == "text":
                content = field("text", MAX_TEXT, True)
                preview = " ".join(content.split())
                title = title or (preview if len(preview) <= 72 else preview[:71].rstrip() + "…")
                extracted = json.dumps([{"label": "", "text": part} for part in passages(content)])
            elif kind == "link":
                attachment_url = safe_link(field("url", 2048, True))
                title = title or urlsplit(attachment_url).hostname or "Reference"
            elif kind == "file":
                upload = request.files.get("file")
                if upload is None or not upload.filename:
                    raise ValueError("Choose a file to upload.")
                filename, blob, extracted = file_content(upload)
                title = title or filename[:160]
            else:
                raise ValueError("Choose text, URL or a file.")
            db().execute("BEGIN IMMEDIATE")
            if selection == "new":
                target_scope = visibility("new_visibility")
                if scope == "team" and target_scope == "draft":
                    raise ValueError("Team evidence requires a team thesis. Choose draft evidence.")
                values = {
                    "title": field("new_title", 160, True),
                    "argument": field("new_argument", 12000),
                    "topics": ", ".join(topic_list(field("new_topics", 200))),
                    "status": "Exploring",
                    "visibility": target_scope,
                    "questions": "",
                    "competing": "",
                    "reviewed": "",
                }
                thesis_id = save_thesis(values, *viewer())
            elif selection:
                if not selection.isascii() or not selection.isdecimal() or len(selection) > 18:
                    raise ValueError("Choose a thesis or create one.")
                target = thesis_or_404(int(selection))
                if target["visibility"] == "draft" and scope == "team":
                    raise ValueError("Team evidence requires a team thesis. Choose draft evidence.")
                thesis_id = target["id"]
            else:
                thesis_id = None

            duplicate = duplicate_reference(attachment_url, thesis_id)
            if duplicate is not None:
                raise ValueError("This URL is already saved here.")
            inserted = db().execute(
                """INSERT INTO sources (thesis_id, added_by, added, title, author, visibility,
                kind, url, filename, file_bytes, passage_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    thesis_id,
                    g.user["id"],
                    now(),
                    title,
                    author,
                    scope,
                    kind,
                    attachment_url,
                    filename,
                    blob,
                    extracted,
                ),
            )
            db().commit()
            return redirect(url_for("views.source", source_id=inserted.lastrowid))
        except ValueError as exc:
            db().rollback()
            return render_template(
                "add.html",
                items=theses(),
                values=request.form,
                problem=str(exc),
                duplicate=duplicate,
            ), 409 if duplicate is not None else 400

    return render_template(
        "add.html",
        items=theses(),
        values={
            "thesis": request.args.get("thesis", ""),
        },
    )


@bp.get("/source/<int:source_id>")
@login_required
def source(source_id: int):
    item = source_or_404(source_id)
    return render_source(item)


def render_source(item: sqlite3.Row, **context):
    parent = thesis_or_404(item["thesis_id"]) if item["thesis_id"] else None
    return render_template(
        "source.html",
        item=item,
        parent=parent,
        extracted=json.loads(item["passage_data"]),
        destinations=theses() if parent is None else [],
        **context,
    )


@bp.post("/source/<int:source_id>/attach")
@login_required
def assign_source(source_id: int):
    item = source_or_404(source_id)
    if item["added_by"] != g.user["id"] or item["thesis_id"] is not None:
        abort(403)
    selection = request.form.get("thesis", "")
    if not selection.isascii() or not selection.isdecimal() or len(selection) > 18:
        abort(400, "Choose a thesis.")
    target = thesis_or_404(int(selection))
    try:
        scope = visibility()
    except ValueError as exc:
        abort(400, str(exc))
    if scope == "team" and target["visibility"] != "team":
        abort(400, "Choose Draft evidence, or attach it to a team thesis.")
    duplicate = duplicate_reference(item["url"], target["id"], excluding=source_id)
    if duplicate is not None:
        return render_source(
            item, problem="This URL is already attached to that thesis.", duplicate=duplicate
        ), 409
    db().execute(
        "UPDATE sources SET thesis_id = ?, visibility = ? WHERE id = ?",
        (target["id"], scope, source_id),
    )
    db().commit()
    return redirect(url_for("views.source", source_id=source_id))


def editable_source(source_id: int) -> sqlite3.Row:
    item = source_or_404(source_id)
    if item["added_by"] != g.user["id"]:
        abort(403, "Only the person who added this source can edit or delete it.")
    return item


@bp.route("/source/<int:source_id>/edit", methods=["GET", "POST"])
@login_required
def edit_source(source_id: int):
    item = editable_source(source_id)
    if request.method == "POST":
        duplicate = None
        try:
            title = field("title", 160, True)
            author = field("author", 160)
            url = safe_link(field("url", 2048, True)) if item["kind"] == "link" else item["url"]
            duplicate = duplicate_reference(url, item["thesis_id"], excluding=source_id)
            if duplicate is not None:
                raise ValueError("This URL is already saved here.")
        except ValueError as exc:
            return render_template(
                "source_edit.html",
                item=item,
                values=request.form,
                problem=str(exc),
                duplicate=duplicate,
            ), 409 if duplicate is not None else 400
        db().execute(
            "UPDATE sources SET title = ?, author = ?, url = ? WHERE id = ?",
            (title, author, url, source_id),
        )
        db().commit()
        return redirect(url_for("views.source", source_id=source_id), code=303)
    return render_template("source_edit.html", item=item, values=item)


@bp.post("/source/<int:source_id>/delete")
@login_required
def delete_source(source_id: int):
    editable_source(source_id)
    # Keep the ID reserved so a deleted citation can never point to a different source.
    db().execute(
        """UPDATE sources SET deleted = 1, thesis_id = NULL, visibility = 'draft',
           title = '', author = '', url = '', filename = '', file_bytes = NULL, passage_data = '[]'
           WHERE id = ?""",
        (source_id,),
    )
    db().commit()
    return redirect(url_for("views.mine"), code=303)


@bp.get("/source/<int:source_id>/download")
@login_required
def download(source_id: int):
    item = source_or_404(source_id)
    if item["kind"] != "file":
        abort(404)
    blob = db().execute("SELECT file_bytes FROM sources WHERE id = ?", (source_id,)).fetchone()
    return send_file(
        io.BytesIO(blob["file_bytes"]),
        as_attachment=True,
        download_name=item["filename"],
        mimetype="application/octet-stream",
    )


@bp.post("/source/<int:source_id>/visibility")
@login_required
def source_sharing(source_id: int):
    item = source_or_404(source_id)
    if g.user["id"] != item["added_by"]:
        abort(403, "Only the person who added this source can change its visibility.")
    target = thesis_or_404(item["thesis_id"]) if item["thesis_id"] else None
    try:
        scope = visibility()
    except ValueError as exc:
        abort(400, str(exc))
    if scope == "team" and (target is None or target["visibility"] != "team"):
        abort(400, "Share the thesis before sharing this source.")
    if scope == "team" and item["visibility"] != "team":
        duplicate = duplicate_reference(item["url"], item["thesis_id"], excluding=source_id)
        if duplicate is not None:
            return render_source(
                item, problem="This URL is already saved on this thesis.", duplicate=duplicate
            ), 409
    db().execute("UPDATE sources SET visibility = ? WHERE id = ?", (scope, source_id))
    db().commit()
    return redirect(url_for("views.source", source_id=source_id))


@bp.route("/ask", methods=["GET", "POST"])
@login_required
def ask():
    question, result, error = "", None, None
    enabled = bool(current_app.config["OPENAI_API_KEY"])
    use_model = request.form.get("use_model") == "yes"
    session_hash = token_hash(session["auth_token"])
    ts = int(time.time())
    if request.method == "POST":
        try:
            question = field("question", 800, True)
        except ValueError as exc:
            error = str(exc)
        else:
            evidence = research.visible_evidence()
            db().rollback()
            result = research.answer(question, evidence, use_model)
            key = secrets.token_urlsafe(24)
            db().execute("BEGIN IMMEDIATE")
            if (
                not db()
                .execute(
                    "SELECT 1 FROM sessions WHERE token_hash = ? AND expires > ?",
                    (session_hash, int(time.time())),
                )
                .fetchone()
            ):
                return redirect(url_for("auth.sign_in"), code=303)
            db().execute("DELETE FROM ask_results WHERE expires <= ?", (ts,))
            db().execute(
                "INSERT INTO ask_results VALUES (?,?,?,?,?)",
                (
                    key,
                    session_hash,
                    ts + 3600,
                    question,
                    json.dumps(
                        {
                            **result,
                            "use_model": use_model,
                            "refs": [item.fingerprint() for item in result["refs"]],
                        }
                    ),
                ),
            )
            db().commit()
            return redirect(url_for("views.ask", result=key), code=303)
    elif saved_key := request.args.get("result"):
        saved = (
            db()
            .execute(
                "SELECT question, result FROM ask_results WHERE id = ? AND session_hash = ? AND expires > ?",
                (saved_key, session_hash, ts),
            )
            .fetchone()
        )
        if saved is None:
            abort(404)
        question = saved["question"]
        result = json.loads(saved["result"])
        use_model = result["use_model"]
        if result["refs"]:
            visible = {item.fingerprint(): item for item in research.visible_evidence()}
            if any(ref not in visible for ref in result["refs"]):
                result = None
                error = "The cited material has changed or is no longer accessible. Ask again."
            else:
                result["refs"] = [visible[ref] for ref in result["refs"]]
    return render_template(
        "ask.html",
        question=question,
        result=result,
        enabled=enabled,
        problem=error,
        use_model=use_model,
    ), 400 if error and request.method == "POST" else 200
