import hashlib
import re
from pathlib import Path

from fakes import Good, settings_for
from fastapi.testclient import TestClient

from signal_atlas.app import create_app
from signal_atlas.db import connect
from signal_atlas.export import edition_markdown
from signal_atlas.pipeline import latest_snapshot, load_signals
from signal_atlas.seed import SIGNALS, seed, validate_signal

ROOT = Path(__file__).resolve().parent.parent


def test_every_published_signal_has_provenance(tmp_path):
    conn = connect(tmp_path / "p.db")
    seed(conn)
    sigs = load_signals(conn)
    assert len(sigs) == len(SIGNALS)
    for s in sigs:
        assert any(e["claim_type"] in ("primary", "corroborated") for e in s["evidence"]), s["id"]
        assert any(e["stance"] == "challenges" for e in s["evidence"]), s["id"]
        for e in s["evidence"]:
            assert e["url"].startswith("https://") and e["source_type"] and e["first_seen_at"] and e["retrieved_at"]
            assert e["claim_type"] in ("primary", "corroborated", "reported")
    md = edition_markdown(latest_snapshot(conn, "2026-11-05"))
    assert "not probabilities" in md and "https://www.sec.gov/Archives/" in md


def test_validation_rejects_unsupported_signals():
    bad = dict(SIGNALS[0], evidence=[(SIGNALS[0]["evidence"][0][0], "reported", "supports", "claim only")])
    errs = validate_signal(bad)
    assert any("primary or independently corroborated" in e for e in errs)
    assert any("counterevidence" in e for e in errs)


BLOCKED = {  # sha256 of disallowed identity/affiliation tokens (kept hashed so the audit itself stays clean)
    "0eaa4b3e1facf2ed4f42dfc21e88b2789fe080d0faf013fef4351e08b2c5f861",
    "fac6a3243ed4705f97a025bb5bc79766fe694d965bb48a29b6c667364c9a2e6c",
    "a1ea2d3fdf2f824161a812976baf9ab1d2f09cd76e6c79a2056ec00899243c0c",
    "1658d13da49eb76eb0c173d4210a3f969bd5fe249390feb3e6d3fd77133a6b8f",
    "b02e06485c54bb8d503d44ab75693665ccfb580a0d5cbd12c488d8c4aab51f37",
    "24cba1263475f27eeaff3b93904b004006720194f2f3c60e7613f109127a4ebb",
    "1ab77b2e9955dd47244cae385e5c004a87897ee8836b4417b95f4d3c6e13c092",
}
SKIP = {".venv", ".git", "data", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "fonts", "screenshots"}


def test_branding_audit_no_identity_or_affiliation_tokens():
    hits = []
    for p in ROOT.rglob("*"):
        if p.is_dir() or any(part in SKIP for part in p.relative_to(ROOT).parts):
            continue
        try:
            text = p.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for w in set(re.findall(r"[a-z0-9]+", text.lower())):
            if hashlib.sha256(w.encode()).hexdigest() in BLOCKED:
                hits.append(str(p.relative_to(ROOT)))
    assert not hits, f"prohibited tokens found in: {sorted(set(hits))}"


def _client(tmp_path, token="t" * 32):
    return TestClient(create_app(settings_for(tmp_path, token), adapters_factory=lambda s: [Good()]))


def test_public_api_and_security_headers(tmp_path):
    with _client(tmp_path) as c:
        r = c.get("/api/status")
        assert r.status_code == 200 and r.json()["schedule"].startswith("08:00 and 16:00")
        assert "default-src 'self'" in r.headers["content-security-policy"]
        e = c.get("/api/edition").json()
        assert e["edition_date"] == "2026-11-05" and len(e["signals"]) == 6
        assert c.get("/api/edition", params={"date": "1999-01-01"}).status_code == 404
        assert c.get("/api/series/poc:composite").status_code == 404  # never fabricated before ingestion
        assert c.get("/").status_code == 200
        assert "Signal Atlas" in c.get("/").text


def test_manual_refresh_auth_and_rate_limit(tmp_path):
    with _client(tmp_path) as c:
        assert c.post("/api/admin/refresh").status_code == 401
        assert c.post("/api/admin/refresh", headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = {"Authorization": "Bearer " + "t" * 32}
        assert c.post("/api/admin/refresh", headers=ok).status_code == 202
        assert c.post("/api/admin/refresh", headers=ok).status_code == 429


def test_failed_auth_lockout(tmp_path):
    with _client(tmp_path) as c:
        for _ in range(5):
            c.post("/api/admin/refresh", headers={"Authorization": "Bearer nope"})
        assert c.post("/api/admin/refresh", headers={"Authorization": "Bearer " + "t" * 32}).status_code == 429


def test_refresh_disabled_without_server_token(tmp_path):
    with _client(tmp_path, token=None) as c:
        assert c.post("/api/admin/refresh", headers={"Authorization": "Bearer x"}).status_code == 503
