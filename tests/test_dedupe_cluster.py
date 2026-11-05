from signal_atlas.adapters.base import RawItem
from signal_atlas.db import connect
from signal_atlas.pipeline import upsert_document
from signal_atlas.urlnorm import canonicalize


def test_canonical_url_variants_collapse():
    assert canonicalize("http://www.Example.com/news/story/?utm_source=x&b=2&a=1&fbclid=z#frag") == \
        "https://example.com/news/story?a=1&b=2"
    assert canonicalize("https://example.com//news/story") == canonicalize("https://EXAMPLE.com/news/story/")
    assert canonicalize("https://example.com/a?id=1") != canonicalize("https://example.com/a?id=2")


def test_dedupe_preserves_first_seen_and_records_revisions(tmp_path):
    conn = connect(tmp_path / "d.db")
    a = RawItem(url="https://milkroad.com/news/x/?utm_medium=email", title="GPU prices rise", source_type="news_brief")
    b = RawItem(url="http://www.milkroad.com/news/x", title="GPU prices rise", source_type="news_brief")
    c = RawItem(url="https://milkroad.com/news/x#top", title="GPU prices rise again", source_type="news_brief")
    id1, s1 = upsert_document(conn, a, "milkroad", "2026-11-05T13:00:00Z")
    id2, s2 = upsert_document(conn, b, "milkroad", "2026-11-05T21:00:00Z")
    id3, s3 = upsert_document(conn, c, "milkroad", "2026-11-06T13:00:00Z")
    assert id1 == id2 == id3 and (s1, s2, s3) == ("new", "unchanged", "updated")
    row = conn.execute("SELECT * FROM documents").fetchone()
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert row["first_seen_at"] == "2026-11-05T13:00:00Z" and row["retrieved_at"] == "2026-11-06T13:00:00Z"
    assert row["url"].endswith("utm_medium=email")  # original link preserved
    assert conn.execute("SELECT COUNT(*) FROM document_revisions").fetchone()[0] == 2


def test_related_stories_cluster_across_sources(tmp_path):
    conn = connect(tmp_path / "c.db")
    t = "2026-11-05T13:00:00Z"
    d1, _ = upsert_document(conn, RawItem(url="https://a.example/1", title="Nvidia H100 GPU rental prices surge as AI demand grows",
                                          source_type="news_headline"), "a", t)
    d2, _ = upsert_document(conn, RawItem(url="https://b.example/2", title="GPU rental prices surge for Nvidia H100 chips",
                                          source_type="podcast"), "b", t)
    d3, _ = upsert_document(conn, RawItem(url="https://c.example/3", title="Oil prices fall on new supply from OPEC",
                                          source_type="news_headline"), "c", t)
    cl = {r["id"]: r["cluster_id"] for r in conn.execute("SELECT id, cluster_id FROM documents")}
    assert cl[d1] == cl[d2] != cl[d3]
