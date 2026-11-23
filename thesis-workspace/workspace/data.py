import json
import sqlite3
import unicodedata
from datetime import datetime, timezone

from flask import abort, g

STATUSES = ("Exploring", "Developing", "Active", "Archived")
THESIS_FIELDS = (
    "title",
    "argument",
    "questions",
    "competing",
    "topics",
    "status",
    "visibility",
    "reviewed",
)
THESIS_QUERY = """
    SELECT t.*, p.name AS owner,
        (SELECT v.token FROM versions v WHERE v.thesis_id = t.id
           ORDER BY v.revision DESC LIMIT 1) AS version_token
    FROM theses t JOIN people p ON t.owner_id = p.id
    WHERE t.space = ? AND (t.visibility = 'team' OR t.owner_id = ?)
"""
SOURCE_QUERY = """
    SELECT s.id, s.thesis_id, s.added_by, s.added, s.title, s.author, s.visibility, s.kind,
           s.url, s.filename, s.passage_data, p.name AS added_name,
           t.title AS thesis_title, owner.name AS thesis_owner
    FROM sources s
    JOIN people p ON s.added_by = p.id
    LEFT JOIN theses t ON s.thesis_id = t.id
    LEFT JOIN people owner ON t.owner_id = owner.id
    WHERE p.space = ? AND s.deleted = 0 AND (t.id IS NULL OR t.visibility = 'team' OR t.owner_id = ?)
        AND ((t.id IS NOT NULL AND s.visibility = 'team') OR s.added_by = ?)
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def db() -> sqlite3.Connection:
    return g.db


def viewer() -> tuple[str, int]:
    return g.user["space"], g.user["id"]


def theses() -> list[sqlite3.Row]:
    return db().execute(THESIS_QUERY + " ORDER BY t.updated DESC, t.id DESC", viewer()).fetchall()


def thesis_or_404(thesis_id: int) -> sqlite3.Row:
    item = db().execute(THESIS_QUERY + " AND t.id = ?", (*viewer(), thesis_id)).fetchone()
    if item is None:
        abort(404)
    return item


def sources(where: str = "", args: tuple = ()) -> list[sqlite3.Row]:
    space, person = viewer()
    return (
        db()
        .execute(SOURCE_QUERY + where + " ORDER BY s.id DESC", (space, person, person, *args))
        .fetchall()
    )


def source_or_404(source_id: int) -> sqlite3.Row:
    items = sources(" AND s.id = ?", (source_id,))
    if not items:
        abort(404)
    return items[0]


def save_thesis(
    values: dict[str, str],
    space: str,
    owner_id: int,
    thesis_id: int | None = None,
) -> int:
    conn = db()
    ts = now()
    values_tuple = tuple(values[field] for field in THESIS_FIELDS)
    if thesis_id is None:
        result = conn.execute(
            """INSERT INTO theses
            (title, argument, questions, competing, topics, status, visibility, reviewed,
             space, owner_id, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (*values_tuple, space, owner_id, ts),
        )
        assert result.lastrowid is not None
        thesis_id = result.lastrowid
    else:
        conn.execute(
            """UPDATE theses SET title=?, argument=?, questions=?, competing=?, topics=?,
            status=?, visibility=?, reviewed=?, updated=? WHERE id=?""",
            (*values_tuple, ts, thesis_id),
        )
    conn.execute(
        """INSERT INTO versions (thesis_id, revision, changed, visibility, snapshot, token)
        SELECT ?, COALESCE(MAX(revision), 0) + 1, ?, ?, ?, lower(hex(randomblob(16)))
        FROM versions WHERE thesis_id = ?""",
        (thesis_id, ts, values["visibility"], json.dumps(values), thesis_id),
    )
    return thesis_id


def name_key(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def name_taken(space: str, name: str, excluding: int = 0) -> bool:
    key = name_key(name)
    people = db().execute("SELECT name FROM people WHERE space = ? AND id != ?", (space, excluding))
    return any(name_key(person["name"]) == key for person in people)


def person(space: str, email: str, name: str) -> int:
    existing = (
        db()
        .execute("SELECT id FROM people WHERE space = ? AND email = ?", (space, email))
        .fetchone()
    )
    if existing is not None:
        return int(existing["id"])
    base = name[:80].strip() or "Team member"
    name = base
    counter = 1
    while name_taken(space, name):
        counter += 1
        suffix = f" ({counter})"
        name = base[: 80 - len(suffix)] + suffix
    row = db().execute(
        "INSERT INTO people (space, email, name) VALUES (?, ?, ?)", (space, email, name)
    )
    assert row.lastrowid is not None
    return row.lastrowid
