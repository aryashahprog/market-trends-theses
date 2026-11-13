from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signal_atlas.adapters.base import ParseError
from signal_atlas.adapters.ramp import RampAiIndexAdapter, headline_adoption

NOW = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
FILLER = "<p>" + "Monthly data on AI adoption and spend from firms on Ramp. " * 12 + "</p>"
TEASER = ("<article>The Census Bureau was undercounting business AI adoption. But it's still far behind Ramp's "
          "estimate showing 46.6% of businesses use AI.</article>")
LEAD = "<p>In October 2026, AI adoption reached 56.8% of U.S. businesses on Ramp, up 1.0 percentage points.</p>"
TABLE = ("<table><tr><th>Metric</th><th>Oct 2026</th><th>Sep 2026</th><th>Change</th></tr>"
         "<tr><td>AI adoption: All businesses</td><td>56.8%</td><td>55.8%</td><td>+1.0 pts</td></tr>"
         "<tr><td>AI adoption: Anthropic</td><td>44.8%</td><td>43.7%</td><td>+1.1 pts</td></tr></table>")
HEAD = ('<head><title>Ramp AI Index</title><meta name="description" content="In October 2026, 56.8% of U.S. '
        'businesses on Ramp paid for AI, up 1.0 points from September."></head>')


class FakeHttp:
    def __init__(self, html: str) -> None:
        self.html = html

    def get(self, url: str, **_: object) -> bytes:
        return self.html.encode()


def fetch(html: str):  # type: ignore[no-untyped-def]
    return RampAiIndexAdapter().fetch(FakeHttp(html), NOW)  # type: ignore[arg-type]


def test_metric_table_wins_over_older_teaser_figures() -> None:
    from signal_atlas.sanitize import strip_html
    assert headline_adoption(strip_html(TEASER + FILLER + TABLE)) == ("Oct 2026", "56.8")


def test_lead_sentence_is_the_fallback() -> None:
    assert headline_adoption("Teaser: 46.6% of businesses use AI. " + LEAD) == ("October 2026", "56.8")
    assert headline_adoption("In October 2026, 56.8% of U.S. businesses on Ramp paid for AI") == ("October 2026", "56.8")


def test_teaser_figures_alone_are_not_a_headline() -> None:
    assert headline_adoption(TEASER) is None


def test_excerpt_does_not_repeat_a_figure_already_in_the_description() -> None:
    item = fetch(HEAD + TEASER + FILLER + TABLE).items[0]
    assert item.meta["figures"] == ["56.8"] and item.meta["adoption_month"] == "Oct 2026"
    assert item.excerpt and "46.6" not in item.excerpt and item.excerpt.count("56.8%") == 1


def test_figure_is_appended_when_the_description_lacks_it() -> None:
    item = fetch("<title>Ramp AI Index</title>" + FILLER + TABLE).items[0]
    assert item.excerpt == "All-business AI adoption, Oct 2026: 56.8%."


def test_missing_headline_is_a_warning_not_a_wrong_number() -> None:
    res = fetch(HEAD.replace("56.8% of U.S. businesses", "most businesses") + TEASER + FILLER)
    assert res.items[0].meta["figures"] == [] and res.warnings


def test_short_page_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        fetch("<p>Access denied</p>")
