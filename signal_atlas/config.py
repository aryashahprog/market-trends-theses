from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

TIMEZONE = "America/New_York"
ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("signal_atlas.config")


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    """A non-negative integer setting; a malformed value falls back to the default instead of crashing startup."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("%s=%r is not an integer; using %d", name, raw, default)
        return default
    if value < minimum:
        log.warning("%s=%d is below %d; using %d", name, value, minimum, default)
        return default
    return value


@dataclass(frozen=True)
class Settings:
    db_path: Path
    admin_token: str | None
    http_user_agent: str
    sec_user_agent: str
    manual_refresh_min_interval_s: int
    stale_grace_minutes: int
    run_scheduler_in_web: bool


def get_settings() -> Settings:
    data_dir = Path(os.environ.get("SIGNAL_ATLAS_DATA_DIR", ROOT / "data"))
    token = os.environ.get("SIGNAL_ATLAS_ADMIN_TOKEN") or None
    if token is not None and len(token) < 24:
        token = None  # too short to be safe; manual refresh stays disabled
    return Settings(
        db_path=Path(os.environ.get("SIGNAL_ATLAS_DB", data_dir / "signal_atlas.db")),
        admin_token=token,
        http_user_agent=os.environ.get(
            "SIGNAL_ATLAS_USER_AGENT",
            "MarketTrendsThesesBot/1.0 (+public-source research; respects robots.txt)",
        ),
        sec_user_agent=os.environ.get("SEC_USER_AGENT", ""),
        manual_refresh_min_interval_s=_int_env("SIGNAL_ATLAS_REFRESH_COOLDOWN_S", 600, minimum=60),
        stale_grace_minutes=_int_env("SIGNAL_ATLAS_STALE_GRACE_MIN", 90),
        run_scheduler_in_web=os.environ.get("SIGNAL_ATLAS_SCHEDULER_IN_WEB", "0") == "1",
    )
