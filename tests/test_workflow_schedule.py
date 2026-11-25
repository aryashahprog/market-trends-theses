import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from signal_atlas.scheduling import SLOTS
from signal_atlas.timeutil import NY

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish.yml"


def _field(spec: str, top: int) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if part == "*":
            out += range(top)
        elif "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return out


def attempts_utc() -> list[tuple[int, int]]:
    crons = re.findall(r'cron:\s*"([^"]+)"', WORKFLOW.read_text())
    assert crons
    times = set()
    for c in crons:
        minute, hour, dom, month, dow = c.split()
        assert (dom, month, dow) == ("*", "*", "*")
        times |= {(h, m) for h in _field(hour, 24) for m in _field(minute, 60)}
    return sorted(times)


def test_every_slot_gets_prompt_and_repeated_attempts_in_edt_and_est():
    times = attempts_utc()
    day = date(2026, 1, 1)
    while day < date(2027, 1, 1):
        for slot in SLOTS:
            at = datetime.combine(day, slot, tzinfo=NY).astimezone(timezone.utc)
            runs = [datetime(at.year, at.month, at.day, h, m, tzinfo=timezone.utc) for h, m in times]
            window = [r for r in runs if at <= r < at + timedelta(hours=4)]
            assert len(window) >= 8, (day, slot, len(window))
            assert window[0] - at <= timedelta(minutes=15), (day, slot, window[0])
        day += timedelta(days=1)


def test_attempts_avoid_the_congested_top_of_the_hour():
    assert all(m not in (0, 1, 2, 3, 4, 5) for _, m in attempts_utc())


def test_pages_deploy_is_retried_once_after_a_transient_failure():
    text = WORKFLOW.read_text()
    first = re.search(r"- id: deploy\n((?:        .*\n)+)", text)
    retry = re.search(r"- id: deploy_retry\n((?:        .*\n)+)", text)
    assert first and retry
    assert "continue-on-error: true" in first.group(1)
    assert "if: steps.deploy.outcome == 'failure'" in retry.group(1) and "deploy-pages" in retry.group(1)
    assert "continue-on-error" not in retry.group(1)  # a second failure still fails the run
    assert "steps.deploy_retry.outputs.page_url" in text
