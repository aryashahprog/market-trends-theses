"""Polite HTTP client: robots.txt, per-host throttling, persistent cache, conditional requests."""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

MAX_BYTES = 6_000_000
MAX_REDIRECTS = 5
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(
        self,
        conn: sqlite3.Connection,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        min_interval_s: float = 1.5,
        respect_robots: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.conn = conn
        self.user_agent = user_agent
        self.min_interval_s = min_interval_s
        self.respect_robots = respect_robots
        self.sleep = sleep
        self.clock = clock
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self.requests_made = 0
        self.client = httpx.Client(
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=False,  # redirects are followed in _fetch so every hop is robots-checked and throttled
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_interval_s - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_hit[host] = self.clock()

    def _allowed(self, url: str, ua: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                self._throttle(parts.netloc)
                r = self.client.get(origin + "/robots.txt", headers={"User-Agent": ua}, follow_redirects=True)
                self.requests_made += 1
                if r.status_code >= 500:
                    parser = None  # unknown policy: do not crawl
                elif r.status_code >= 400:
                    assert parser is not None
                    parser.parse([])
                else:
                    assert parser is not None
                    parser.parse(r.text.splitlines())
            except httpx.HTTPError:
                parser = None
            self._robots[origin] = parser
        rp = self._robots[origin]
        return bool(rp and rp.can_fetch(ua, url))

    def get(self, url: str, *, ttl_s: float = 3600, user_agent: str | None = None,
            accept: str = "*/*") -> bytes:
        ua = user_agent or self.user_agent
        row = self.conn.execute(
            "SELECT etag, last_modified, fetched_at, body FROM http_cache WHERE url=?", (url,)
        ).fetchone()
        now = self.clock()
        if row and now - row["fetched_at"] < ttl_s:
            return bytes(row["body"])
        headers = {"User-Agent": ua, "Accept": accept}
        if row and row["etag"]:
            headers["If-None-Match"] = row["etag"]
        if row and row["last_modified"]:
            headers["If-Modified-Since"] = row["last_modified"]
        r, body = self._fetch(url, headers, ua)
        if r.status_code == 304 and row:
            self.conn.execute("UPDATE http_cache SET fetched_at=? WHERE url=?", (now, url))
            return bytes(row["body"])
        if r.status_code in (401, 402, 403):
            raise FetchError(f"HTTP {r.status_code} (access restricted) for {urlsplit(url).netloc}; not bypassed")
        if r.status_code == 429:
            raise FetchError(f"HTTP 429 rate limited by {urlsplit(url).netloc}")
        if r.status_code >= 300:
            raise FetchError(f"HTTP {r.status_code} for {urlsplit(url).netloc}")
        self.conn.execute(
            "INSERT INTO http_cache(url, etag, last_modified, fetched_at, status, body) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET etag=excluded.etag, last_modified=excluded.last_modified, "
            "fetched_at=excluded.fetched_at, status=excluded.status, body=excluded.body",
            (url, r.headers.get("etag"), r.headers.get("last-modified"), now, r.status_code, body),
        )
        return body

    def _fetch(self, url: str, headers: dict[str, str], ua: str) -> tuple[httpx.Response, bytes]:
        """GET url, following redirects only to http(s) targets that robots.txt allows, and reading at most
        MAX_BYTES of body. Returns the final response and its body (empty for errors and 304s)."""
        for _ in range(MAX_REDIRECTS + 1):
            host = urlsplit(url).netloc
            if not self._allowed(url, ua):
                raise FetchError(f"robots.txt disallows or is unavailable for {host}")
            self._throttle(host)
            try:
                with self.client.stream("GET", url, headers=headers) as r:
                    self.requests_made += 1
                    location = r.headers.get("location")
                    if r.status_code in REDIRECT_CODES and location:
                        url = str(r.url.join(location))
                        if urlsplit(url).scheme not in ("http", "https"):
                            raise FetchError(f"redirect from {host} to a non-HTTP URL")
                        # validators belong to the originally requested resource, not the redirect target
                        headers = {k: v for k, v in headers.items()
                                   if k not in ("If-None-Match", "If-Modified-Since")}
                        continue
                    if r.status_code >= 300:
                        return r, b""
                    declared = r.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > MAX_BYTES:
                        raise FetchError(f"response too large from {host}")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise FetchError(f"response too large from {host}")
                        chunks.append(chunk)
                    return r, b"".join(chunks)
            except httpx.HTTPError as e:
                raise FetchError(f"network error for {host}: {type(e).__name__}") from e
        raise FetchError(f"too many redirects starting from {urlsplit(url).netloc}")
