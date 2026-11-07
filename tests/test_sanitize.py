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
