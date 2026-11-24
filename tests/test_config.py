import logging
from pathlib import Path

import pytest

from signal_atlas.config import get_settings

VARS = ("SIGNAL_ATLAS_DATA_DIR", "SIGNAL_ATLAS_DB", "SIGNAL_ATLAS_ADMIN_TOKEN", "SIGNAL_ATLAS_USER_AGENT",
        "SEC_USER_AGENT", "SIGNAL_ATLAS_REFRESH_COOLDOWN_S", "SIGNAL_ATLAS_STALE_GRACE_MIN",
        "SIGNAL_ATLAS_SCHEDULER_IN_WEB")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)


def test_defaults():
    s = get_settings()
    assert s.db_path.name == "signal_atlas.db" and s.db_path.parent.name == "data"
    assert s.admin_token is None and s.sec_user_agent == ""
    assert (s.manual_refresh_min_interval_s, s.stale_grace_minutes, s.run_scheduler_in_web) == (600, 90, False)


def test_data_dir_and_explicit_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNAL_ATLAS_DATA_DIR", str(tmp_path))
    assert get_settings().db_path == tmp_path / "signal_atlas.db"
    monkeypatch.setenv("SIGNAL_ATLAS_DB", str(tmp_path / "other.db"))
    assert get_settings().db_path == Path(tmp_path / "other.db")


@pytest.mark.parametrize("token, kept", [("x" * 23, False), ("x" * 24, True), ("", False)])
def test_short_admin_tokens_disable_manual_refresh(monkeypatch, token, kept):
    monkeypatch.setenv("SIGNAL_ATLAS_ADMIN_TOKEN", token)
    assert (get_settings().admin_token == token) is kept


def test_valid_integers_are_used(monkeypatch):
    monkeypatch.setenv("SIGNAL_ATLAS_REFRESH_COOLDOWN_S", " 900 ")
    monkeypatch.setenv("SIGNAL_ATLAS_STALE_GRACE_MIN", "0")
    s = get_settings()
    assert (s.manual_refresh_min_interval_s, s.stale_grace_minutes) == (900, 0)


@pytest.mark.parametrize("cooldown, grace", [("ten", "1.5"), ("-5", "-1"), ("30", "")])
def test_malformed_integers_fall_back_with_a_warning(monkeypatch, caplog, cooldown, grace):
    monkeypatch.setenv("SIGNAL_ATLAS_REFRESH_COOLDOWN_S", cooldown)
    monkeypatch.setenv("SIGNAL_ATLAS_STALE_GRACE_MIN", grace)
    with caplog.at_level(logging.WARNING, logger="signal_atlas.config"):
        s = get_settings()
    assert (s.manual_refresh_min_interval_s, s.stale_grace_minutes) == (600, 90)
    assert "SIGNAL_ATLAS_REFRESH_COOLDOWN_S" in caplog.text


def test_scheduler_flag_needs_exactly_one(monkeypatch):
    monkeypatch.setenv("SIGNAL_ATLAS_SCHEDULER_IN_WEB", "true")
    assert get_settings().run_scheduler_in_web is False
    monkeypatch.setenv("SIGNAL_ATLAS_SCHEDULER_IN_WEB", "1")
    assert get_settings().run_scheduler_in_web is True
