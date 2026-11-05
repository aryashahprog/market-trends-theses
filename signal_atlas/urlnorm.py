from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src", "cmpid",
    "mod", "igshid", "yclid", "_hsenc", "_hsmi", "mkt_tok", "guccounter", "si", "feature",
}


def canonicalize(url: str) -> str:
    """Stable identity for a URL: https, lowercase host without www, no fragment,
    no tracking parameters, sorted query, no trailing slash."""
    p = urlsplit(url.strip())
    scheme = (p.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    host = (p.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    netloc = host if p.port in (None, 80, 443) else f"{host}:{p.port}"
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    path = quote(unquote(path), safe="/:@!$&'()*+,;=-._~")
    query = sorted(
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in TRACKING_KEYS)
    )
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))
