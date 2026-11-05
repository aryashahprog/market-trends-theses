"""Scraped content is untrusted: reduce it to short plain text before storage."""
from __future__ import annotations

import hashlib
import html
import re

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def strip_html(raw: str) -> str:
    s = re.sub(r"<(script|style|noscript|template|svg)\b.*?</\1\s*>", " ", raw, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = _CTRL.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_text(raw: str | None, limit: int = 280) -> str:
    if not raw:
        return ""
    s = strip_html(raw)
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:-–— ") + "…"


def content_hash(*parts: str | None) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def meta_content(page: str, *names: str) -> str | None:
    for name in names:
        for pat in (
            rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:name|property)=["\']{re.escape(name)}["\']',
        ):
            m = re.search(pat, page, flags=re.I)
            if m and m.group(1).strip():
                return html.unescape(m.group(1)).strip()
    return None


def page_title(page: str) -> str | None:
    t = meta_content(page, "og:title", "twitter:title")
    if t:
        return clean_text(t, 200)
    m = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.S | re.I)
    return clean_text(m.group(1), 200) if m else None
