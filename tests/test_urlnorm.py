import pytest

from signal_atlas.urlnorm import canonicalize


@pytest.mark.parametrize("url, expected", [
    ("http://www.Example.com:80/a/?utm_source=x&b=2&a=1&fbclid=z#frag", "https://example.com/a?a=1&b=2"),
    ("https://example.com:443/a", "https://example.com/a"),
    ("https://example.com:8443/a", "https://example.com:8443/a"),
    ("https://example.com:80/a", "https://example.com:80/a"),
    ("https://example.com./a", "https://example.com/a"),
    ("https://example.com/caf%C3%A9", "https://example.com/caf%C3%A9"),
    ("https://example.com/a%3Fb", "https://example.com/a%3Fb"),
    ("https://example.com/?q=a%20b", "https://example.com/?q=a+b"),
    ("//example.com/x", "https://example.com/x"),
])
def test_canonical_forms(url, expected):
    assert canonicalize(url) == expected


def test_encoded_slash_stays_distinct_from_path_separator():
    assert canonicalize("https://example.com/a%2Fb") == "https://example.com/a%2Fb"
    assert canonicalize("https://example.com/a%2fb") == "https://example.com/a%2Fb"
    assert canonicalize("https://example.com/a%2Fb") != canonicalize("https://example.com/a/b")


def test_ipv6_host_keeps_brackets():
    assert canonicalize("https://[2001:DB8::1]:443/x") == "https://[2001:db8::1]/x"
    assert canonicalize("https://[2001:db8::1]:8080/x") == "https://[2001:db8::1]:8080/x"


@pytest.mark.parametrize("url", ["https://example.com:abc/x", "https://example.com:99999/x",
                                 "https://user@example.com:12ab/x", "https://[::1]:bad/x"])
def test_malformed_port_does_not_raise(url):
    out = canonicalize(url)
    assert out.startswith("https://") and out.endswith("/x")


def test_tracking_params_removed_but_content_params_kept():
    assert canonicalize("https://example.com/a?id=1&UTM_medium=e&mod=rss&gclid=g") == "https://example.com/a?id=1"
    assert canonicalize("https://example.com/a?id=1") != canonicalize("https://example.com/a?id=2")
