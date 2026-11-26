import sys
from datetime import timedelta

import pytest

from signal_atlas import cli
from signal_atlas.db import connect
from signal_atlas.scheduling import previous_slot
from signal_atlas.timeutil import iso, utcnow


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIGNAL_ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SIGNAL_ATLAS_DB", raising=False)

    def _run(*args: str) -> list[str]:
        monkeypatch.setattr(sys, "argv", ["signal-atlas", *args])
        cli.main()
        return capsys.readouterr().out.splitlines()

    _run.db = tmp_path / "signal_atlas.db"  # type: ignore[attr-defined]
    return _run


def _record_run(db, trigger: str, status: str, finished_offset: timedelta) -> None:  # type: ignore[no-untyped-def]
    at = iso(previous_slot(utcnow()) + finished_offset)
    connect(db).execute("INSERT INTO pipeline_runs(trigger, started_at, finished_at, status) VALUES (?,?,?,?)",
                        (trigger, at, at, status))


def test_seed_loads_once_then_only_syncs(run):
    assert run("seed") == ["seeded"]
    assert run("seed") == ["already seeded; editorial content synced"]


def test_due_prints_exactly_one_github_output_line_and_seeding_is_not_an_ingest(run):
    # The workflow appends stdout to $GITHUB_OUTPUT, so anything besides the one key=value line would break it.
    run("seed")
    assert run("due") == ["due=true"]


@pytest.mark.parametrize("trigger,status,offset,due", [
    ("scheduled", "success", timedelta(minutes=5), "false"),
    ("cli", "partial", timedelta(minutes=5), "false"),  # one source failing still covers the slot
    ("catch-up", "success", timedelta(0), "false"),
    ("cli", "failed", timedelta(minutes=5), "true"),  # a failed ingest is retried by the next attempt
    ("scheduled", "success", -timedelta(minutes=1), "true"),  # succeeded only before the latest slot
])
def test_due_reflects_the_latest_successful_ingest_against_the_latest_slot(run, trigger, status, offset, due):
    _record_run(run.db, trigger, status, offset)
    assert run("due") == [f"due={due}"]


def test_a_failure_after_a_success_does_not_make_the_slot_due_again(run):
    _record_run(run.db, "scheduled", "success", timedelta(minutes=5))
    _record_run(run.db, "cli", "failed", timedelta(minutes=30))
    assert run("due") == ["due=false"]


def test_schedule_lists_six_upcoming_slots_in_order(run):
    lines = run("schedule")
    assert len(lines) == 6
    utc = [line.split(" | ")[1] for line in lines]
    assert utc == sorted(utc) and len(set(utc)) == 6
    assert all(" 08:00 " in line or " 16:00 " in line for line in lines)


def test_pack_drops_the_http_cache(run):
    conn = connect(run.db)
    conn.execute("INSERT INTO http_cache(url, fetched_at, status, body) VALUES ('https://example.com/', 0, 200, x'00')")
    conn.close()
    assert run("pack")[0].startswith("packed ")
    assert connect(run.db).execute("SELECT COUNT(*) FROM http_cache").fetchone()[0] == 0


def test_an_unknown_command_exits_with_usage_error(run):
    with pytest.raises(SystemExit) as e:
        run("nope")
    assert e.value.code == 2
