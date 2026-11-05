import copy
from datetime import datetime, timezone

from fakes import Good, null_fetcher, settings_for

from signal_atlas.db import connect, dumps, loads
from signal_atlas.export import edition_markdown
from signal_atlas.pipeline import (
    build_edition,
    get_status,
    latest_snapshot,
    match_document,
    match_rule,
    run_pipeline,
    write_snapshot,
)
from signal_atlas.seed import SIGNALS, seed, sync_content, validate_signal

RULES = {s["id"]: s["match"] for s in SIGNALS}


def test_every_thesis_has_structured_business_relevance():
    for s in SIGNALS:
        assert not validate_signal(s), s["id"]
        assert 2 <= len(s["audiences"]) <= 4 and s["implications"] and s["caveats"]
        assert len({a["role"] for a in s["audiences"]}) >= 2, f"{s['id']} should distinguish roles"


def test_validation_rejects_incomplete_audience():
    bad = dict(SIGNALS[0], audiences=[{"segment": "Enterprises", "role": "fan", "who": "x"}])
    errs = validate_signal(bad)
    assert any("role must be" in e for e in errs) and any("missing impact" in e for e in errs)


def test_gpu_headline_is_scoped_to_evidence():
    gpu = next(s for s in SIGNALS if s["id"] == "gpu-rent-vs-token-deflation")
    assert "older and mid-generation" in gpu["title"]
    assert "scarcer" not in gpu["title"].lower()
    text = " ".join(gpu["caveats"]).lower()
    assert "not directly comparable" in text and "inference" in text and "quality" in text


def test_crypto_headline_no_longer_matches_enterprise_ai():
    eth = "Ethereum's Bull Case Is Getting INSANE - Here Are 3 Reasons Why adoption by AI agents"
    assert match_document(eth, RULES["enterprise-ai-spend-compounding"]) is None
    assert all(match_document(eth, r) is None for r in RULES.values())


def test_match_requires_anchor_plus_context_and_explains_why():
    rule = RULES["gpu-rent-vs-token-deflation"]
    assert match_document("Token prices and inference costs are falling", rule) is None  # context only
    hit = match_document("Nvidia H100 rental prices climb", rule)
    assert hit and "h100" in hit["anchors"] and hit["why"].startswith("Names h100")
    legacy = match_rule({"match_terms": ["gpu", "rental"], "match_min": 2, "title": "t"})
    assert match_document("gpu rental", legacy)


def test_unreviewed_mentions_do_not_affect_ranking_or_evidence(tmp_path):
    s = settings_for(tmp_path)
    conn = connect(s.db_path)
    seed(conn)
    before = {x["id"]: x["scores"] for x in latest_snapshot(conn)["signals"]}
    run_pipeline(conn, s, "cli", adapters=[Good()], fetcher=null_fetcher(conn))
    snap = latest_snapshot(conn)
    gpu = next(x for x in snap["signals"] if x["id"] == "gpu-rent-vs-token-deflation")
    assert gpu["unreviewed_mentions"] and gpu["unreviewed_mentions"][0]["terms"]["why"]
    assert gpu["scores"]["evidence"] == before[gpu["id"]]["evidence"]
    assert gpu["scores"]["novelty"] == before[gpu["id"]]["novelty"]


def test_sync_content_revises_without_rewriting_archived_snapshots(tmp_path):
    conn = connect(tmp_path / "s.db")
    seed(conn)
    old = SIGNALS[0]
    conn.execute("UPDATE signals SET data=? WHERE id=?",
                 (dumps({**{k: v for k, v in old.items() if k not in ("id", "evidence")}, "title": "Old headline"}), old["id"]))
    write_snapshot(conn, None, datetime(2026, 11, 5, 20, tzinfo=timezone.utc))  # archived Nov 5 edition, old headline
    archived = conn.execute("SELECT id, payload FROM edition_snapshots").fetchall()
    n = sync_content(conn, datetime(2026, 11, 6, 14, tzinfo=timezone.utc))
    assert n == 1
    for r in archived:  # untouched
        assert conn.execute("SELECT payload FROM edition_snapshots WHERE id=?", (r["id"],)).fetchone()[0] == r["payload"]
    new = latest_snapshot(conn, "2026-11-06")
    gpu = next(x for x in new["signals"] if x["id"] == old["id"])
    assert gpu["title"] == old["title"] and gpu["evidence_reviewed_at"] == "2026-11-05T15:45:00Z"
    assert gpu["since_last"]["revised"][0]["from"] == "Old headline"
    assert sync_content(conn) == 0  # idempotent


def test_since_last_edition_only_when_history_supports_it(tmp_path):
    conn = connect(tmp_path / "h.db")
    seed(conn)
    first = latest_snapshot(conn, "2026-11-05")
    assert not any("since_last" in s for s in first["signals"])
    now = datetime(2026, 11, 6, 13, tzinfo=timezone.utc)
    same = build_edition(conn, "2026-11-06", now, None)
    assert not any("since_last" in s for s in same["signals"])  # nothing changed -> section omitted
    row = conn.execute("SELECT data FROM signals WHERE id='mission-critical-private-5g'").fetchone()
    conn.execute("UPDATE signals SET data=? WHERE id='mission-critical-private-5g'",
                 (dumps({**loads(row["data"]), "confidence": "Medium"}),))
    snap = write_snapshot(conn, None, now)
    ch = next(s for s in snap["signals"] if s["id"] == "mission-critical-private-5g")["since_last"]
    assert ch["confidence"] == {"from": "Low", "to": "Medium"} and ch["previous_edition"] == "2026-11-05"


def test_export_includes_business_sections(tmp_path):
    conn = connect(tmp_path / "e.db")
    seed(conn)
    md = edition_markdown(latest_snapshot(conn))
    for heading in ("### The takeaway", "### Who this matters to", "### What changed", "### Business implications",
                    "### What could change our view", "### Sources and methodology", "Trigger to watch"):
        assert heading in md
    assert md.count("### Who this matters to") == len(SIGNALS)


def test_partial_refresh_summary_is_plain_language(tmp_path):
    from fakes import Boom
    s = settings_for(tmp_path)
    conn = connect(s.db_path)
    seed(conn)
    run_pipeline(conn, s, "cli", adapters=[Good(), Boom()], fetcher=null_fetcher(conn))
    rs = get_status(conn, s)["refresh_summary"]
    assert rs["status"] == "partial" and rs["ok"] == 1 and rs["total"] == 2
    assert rs["issues"] == [{"source": "Failing source", "status": "failed",
                             "reason": "access restricted by the publisher (not bypassed)"}]


def test_key_figures_cite_registered_sources_and_reach_exports(tmp_path):
    figs = {s["id"]: s.get("figures") or [] for s in SIGNALS}
    assert figs["memory-substrate-reallocation"][0]["bars"][1]["value"] == 7318
    bad = copy.deepcopy(next(s for s in SIGNALS if s.get("figures")))
    bad["figures"][0]["source_url"] = "https://example.com/unreviewed"
    assert any("figure" in e for e in validate_signal(bad))
    conn = connect(tmp_path / "f.db")
    seed(conn)
    md = edition_markdown(latest_snapshot(conn))
    assert "**Figure — Intel Q3 revenue by segment**" in md and "7,318" in md
