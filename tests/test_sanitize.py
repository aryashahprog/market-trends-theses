import time

from signal_atlas.sanitize import clean_text, content_hash, meta_content, page_title, strip_html


def test_meta_content_keeps_apostrophes_inside_double_quotes():
    page = '<meta property="og:title" content="Nvidia\'s data-center sales jump">'
    assert meta_content(page, "og:title") == "Nvidia's data-center sales jump"


def test_meta_content_keeps_double_quotes_inside_single_quotes():
    page = "<meta content='He said \"capex is peaking\"' name='description'>"
    assert meta_content(page, "description") == 'He said "capex is peaking"'


def test_meta_content_unescapes_entities_and_falls_back_to_later_names():
    page = '<meta name="description" content="  "><meta property="og:description" content="AI &amp; power">'
    assert meta_content(page, "description", "og:description") == "AI & power"
    assert meta_content(page, "twitter:description") is None


def test_page_title_prefers_og_title_then_title_tag():
    assert page_title('<meta property="og:title" content="Rate\'s path"><title>Other</title>') == "Rate's path"
    assert page_title("<title>\n  GPU <b>prices</b> fall\n</title>") == "GPU prices fall"
    assert page_title("<p>no title</p>") is None


def test_strip_html_drops_scripts_comments_and_control_chars():
    raw = "<script>alert(1)</script><!-- hidden --><p>Hello\u200b <i>world</i></p><style>p{}</style>"
    assert strip_html(raw) == "Hello world"


def test_clean_text_truncates_on_word_boundary():
    assert clean_text(None) == ""
    assert clean_text("short") == "short"
    assert clean_text("alpha beta, gamma delta", limit=12) == "alpha beta…"


def test_content_hash_separates_parts():
    assert content_hash("ab", "c") != content_hash("a", "bc")
    assert content_hash(None) == content_hash("")


def test_meta_content_handles_attribute_order_case_unquoted_values_and_gt_in_values():
    page = ("<META CONTENT=\"a > b\" Property=\"OG:Title\"/>"
            "<meta data-x='1' content=plain name=description>"
            "<meta property=\"article:published_time\" content=\"2026-11-17T09:00:00Z\" />")
    assert meta_content(page, "og:title") == "a > b"
    assert meta_content(page, "description") == "plain"
    assert meta_content(page, "article:published_time") == "2026-11-17T09:00:00Z"


def test_meta_content_ignores_unterminated_tags_and_other_attributes():
    assert meta_content('<meta name="description" content="never closed', "description") is None
    assert meta_content('<meta name="og:title" value="x" content="">', "og:title") is None


def test_meta_content_is_linear_when_a_name_is_missing():
    # Inline JSON (quotes, no ">") made the previous regex backtrack quadratically: ~6 s here, ~20 s per real page.
    head = "".join(f'<meta name="k{i}" content="v"/>' for i in range(4))
    page = "<head>" + head + "</head><script>" + '{"k":"v"},' * 2000 + "</script>"
    start = time.perf_counter()
    assert meta_content(page, "article:published_time") is None
    assert time.perf_counter() - start < 1.0
