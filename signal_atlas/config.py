from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

TIMEZONE = "America/New_York"
ROOT = Path(__file__).resolve().parent.parent


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
            "SignalAtlasBot/1.0 (+public-source research; respects robots.txt)",
        ),
        sec_user_agent=os.environ.get("SEC_USER_AGENT", ""),
        manual_refresh_min_interval_s=int(os.environ.get("SIGNAL_ATLAS_REFRESH_COOLDOWN_S", "600")),
        stale_grace_minutes=int(os.environ.get("SIGNAL_ATLAS_STALE_GRACE_MIN", "90")),
        run_scheduler_in_web=os.environ.get("SIGNAL_ATLAS_SCHEDULER_IN_WEB", "0") == "1",
    )
