from __future__ import annotations

import re
from urllib.parse import SplitResult, parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src", "cmpid",
    "mod", "igshid", "yclid", "_hsenc", "_hsmi", "mkt_tok", "guccounter", "si", "feature",
}


DEFAULT_PORTS = {"http": 80, "https": 443}
_ENCODED_SLASH = re.compile("%2f", re.IGNORECASE)


def _port(p: SplitResult) -> str | None:
    try:
        port = p.port
    except ValueError:  # e.g. "host:abc" or out-of-range: keep the raw text rather than fail the whole source
        raw = p.netloc.rpartition("@")[2]
        return raw.rpartition("]")[2].partition(":")[2] or None
    return None if port is None else str(port)


def canonicalize(url: str) -> str:
    """Stable identity for a URL: https, lowercase host without www, no default port, no fragment,
    no tracking parameters, sorted query, no trailing slash. Never raises on malformed input."""
    p = urlsplit(url.strip())
    original_scheme = (p.scheme or "https").lower()
    scheme = "https" if original_scheme == "http" else original_scheme
    host = (p.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if ":" in host:
        host = f"[{host}]"
    port = _port(p)
    netloc = host if port in (None, str(DEFAULT_PORTS.get(original_scheme))) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    # %2F inside a segment is data, not a separator: normalize each piece but keep it encoded.
    path = "%2F".join(quote(unquote(part), safe="/:@!$&'()*+,;=-._~") for part in _ENCODED_SLASH.split(path))
    query = sorted(
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in TRACKING_KEYS)
    )
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))
