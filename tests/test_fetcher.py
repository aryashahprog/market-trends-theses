import httpx
import pytest

from signal_atlas import fetcher as fetcher_mod
from signal_atlas.db import connect
from signal_atlas.fetcher import Fetcher, FetchError

ROBOTS = {
    "a.example": "User-agent: *\nDisallow: /private\n",
    "b.example": "User-agent: *\nDisallow: /\n",
    "c.example": "",
}


def make(tmp_path, routes, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(f"{req.url.host}{req.url.path}")
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS.get(req.url.host, ""))
        return routes(req)

    conn = connect(tmp_path / "f.db")
    return Fetcher(conn, "MarketTrendsThesesTest", transport=httpx.MockTransport(handler), sleep=lambda s: None)


def redirect(to: str, code: int = 301) -> httpx.Response:
    return httpx.Response(code, headers={"location": to})


def test_redirect_into_disallowed_path_is_not_fetched(tmp_path):
    calls: list[str] = []
    f = make(tmp_path, lambda r: redirect("/private/x") if r.url.path == "/old" else httpx.Response(200, text="secret"),
             calls)
    with pytest.raises(FetchError, match="robots"):
        f.get("https://a.example/old")
    assert "a.example/private/x" not in calls


def test_cross_host_redirect_checks_the_target_hosts_robots(tmp_path):
    calls: list[str] = []
    f = make(tmp_path, lambda r: redirect("https://b.example/page") if r.url.host == "a.example"
             else httpx.Response(200, text="x"), calls)
    with pytest.raises(FetchError, match="robots.*b.example"):
        f.get("https://a.example/moved")
    assert "b.example/robots.txt" in calls and "b.example/page" not in calls


def test_allowed_redirect_is_followed_and_cached_under_requested_url(tmp_path):
    calls: list[str] = []
    f = make(tmp_path, lambda r: redirect("https://c.example/new", 308) if r.url.path == "/old"
             else httpx.Response(200, text="body", headers={"etag": '"e1"'}), calls)
    assert f.get("https://a.example/old") == b"body"
    n = len(calls)
    assert f.get("https://a.example/old") == b"body" and len(calls) == n
    row = f.conn.execute("SELECT status, etag FROM http_cache WHERE url='https://a.example/old'").fetchone()
    assert row["status"] == 200 and row["etag"] == '"e1"'


def test_validators_are_not_sent_to_a_redirect_target(tmp_path):
    seen: list[dict[str, str]] = []

    def routes(r: httpx.Request) -> httpx.Response:
        seen.append({k: r.headers.get(k, "") for k in ("if-none-match", "if-modified-since")})
        if r.url.path == "/old" and len(seen) > 1:
            return redirect("/new")
        return httpx.Response(200, text="v", headers={"etag": '"old"', "last-modified": "Mon, 02 Nov 2026 00:00:00 GMT"})

    f = make(tmp_path, routes)
    f.get("https://a.example/old")
    f.get("https://a.example/old", ttl_s=0)
    assert seen[1]["if-none-match"] == '"old"'
    assert seen[2] == {"if-none-match": "", "if-modified-since": ""}


def test_redirect_loop_and_non_http_target_fail(tmp_path):
    f = make(tmp_path, lambda r: redirect(r.url.path + "x"))
    with pytest.raises(FetchError, match="too many redirects"):
        f.get("https://a.example/loop")
    g = make(tmp_path, lambda r: redirect("ftp://a.example/file"))
    with pytest.raises(FetchError, match="non-HTTP"):
        g.get("https://a.example/ftp")


def test_redirect_without_location_is_an_error_not_a_cached_empty_body(tmp_path):
    f = make(tmp_path, lambda r: httpx.Response(302))
    with pytest.raises(FetchError, match="HTTP 302"):
        f.get("https://a.example/x")
    assert f.conn.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0] == 0


def test_oversized_bodies_are_rejected_while_streaming(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher_mod, "MAX_BYTES", 10)
    pulled: list[int] = []

    def chunks():
        for i in range(100):
            pulled.append(i)
            yield b"0123456789"

    f = make(tmp_path, lambda r: httpx.Response(200, content=chunks()) if r.url.path == "/stream"
             else httpx.Response(200, content=b"x" * 11))
    with pytest.raises(FetchError, match="too large"):
        f.get("https://a.example/stream")
    assert len(pulled) < 100  # stopped reading instead of buffering the whole body
    with pytest.raises(FetchError, match="too large"):
        f.get("https://a.example/declared")


def test_redirected_robots_txt_is_followed(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "a.example" and req.url.path == "/robots.txt":
            return redirect("https://www.a.example/robots.txt")
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="ok")

    f = Fetcher(connect(tmp_path / "r.db"), "MarketTrendsThesesTest", transport=httpx.MockTransport(handler),
                sleep=lambda s: None)
    assert f.get("https://a.example/ok") == b"ok"
    with pytest.raises(FetchError, match="robots"):
        f.get("https://a.example/private/doc")
