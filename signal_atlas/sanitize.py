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


_META_TAG = re.compile(r"<meta\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.I)
_ATTR = re.compile(r"""([^\s=/>"']+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))""")


def _meta_tags(page: str) -> list[dict[str, str]]:
    tags = []
    for tag in _META_TAG.finditer(page):
        tags.append({m.group(1).lower(): next(v for v in m.groups()[1:] if v is not None)
                     for m in _ATTR.finditer(tag.group(0), 5)})
    return tags


def meta_content(page: str, *names: str) -> str | None:
    """Content of the first non-empty <meta name|property=...> among names, in priority order.
    Tags are tokenised once, so a missing name costs a linear scan instead of regex backtracking."""
    tags = _meta_tags(page)
    for name in names:
        for attrs in tags:
            key = attrs.get("name") or attrs.get("property") or ""
            value = html.unescape(attrs.get("content", "")).strip()
            if key.lower() == name.lower() and value:
                return value
    return None


def page_title(page: str) -> str | None:
    t = meta_content(page, "og:title", "twitter:title")
    if t:
        return clean_text(t, 200)
    m = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.S | re.I)
    return clean_text(m.group(1), 200) if m else None
