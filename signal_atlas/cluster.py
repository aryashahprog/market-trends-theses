"""Lightweight related-story clustering on title tokens."""
from __future__ import annotations

import re
import sqlite3
from datetime import timedelta

from .timeutil import iso, parse_iso

STOP = set(
    "a an and are as at be but by for from has have how in into is it its just new not of on or "
    "our out over says that the their this to up was what when where which who why will with you "
    "your after amid about more most than vs could may might now week today here".split()
)


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9\-\.&]*[a-z0-9]|[a-z0-9]", text.lower())
    return {w for w in words if w not in STOP and len(w) > 2}


def similarity(a: set[str], b: set[str]) -> tuple[float, int]:
    if not a or not b:
        return 0.0, 0
    inter = len(a & b)
    return inter / len(a | b), inter


def assign_cluster(conn: sqlite3.Connection, doc_id: int, title: str, now_iso: str,
                   window_days: int = 14, threshold: float = 0.3, min_overlap: int = 2) -> int:
    now = parse_iso(now_iso)
    assert now is not None
    since = iso(now - timedelta(days=window_days))
    mine = tokens(title)
    best: tuple[float, int | None] = (0.0, None)
    rows = conn.execute(
        "SELECT id, title, cluster_id FROM documents WHERE id != ? AND cluster_id IS NOT NULL AND first_seen_at >= ?",
        (doc_id, since),
    ).fetchall()
    for r in rows:
        score, overlap = similarity(mine, tokens(r["title"]))
        if overlap >= min_overlap and score >= threshold and score > best[0]:
            best = (score, r["cluster_id"])
    cluster_id = best[1]
    if cluster_id is None:
        cur = conn.execute(
            "INSERT INTO clusters(label, created_at, updated_at) VALUES (?,?,?)", (title[:200], now_iso, now_iso)
        )
        cluster_id = int(cur.lastrowid or 0)
    else:
        conn.execute("UPDATE clusters SET updated_at=? WHERE id=?", (now_iso, cluster_id))
    conn.execute("UPDATE documents SET cluster_id=? WHERE id=?", (cluster_id, doc_id))
    return cluster_id
