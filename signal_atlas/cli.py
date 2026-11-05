from __future__ import annotations

import argparse
import json
import logging

from .config import get_settings
from .db import connect
from .pipeline import get_status, run_pipeline
from .scheduling import next_slot
from .seed import seed_if_empty
from .timeutil import NY, utcnow


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="signal-atlas")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="load the verified first edition if the database is empty")
    sub.add_parser("ingest", help="run one ingestion pass now (for cron or ops)")
    sub.add_parser("status", help="print pipeline status as JSON")
    sub.add_parser("schedule", help="print the next six scheduled refresh times")
    args = p.parse_args()
    settings = get_settings()
    conn = connect(settings.db_path)
    if args.cmd == "seed":
        print("seeded" if seed_if_empty(conn) else "already seeded")
    elif args.cmd == "ingest":
        seed_if_empty(conn)
        print(json.dumps(run_pipeline(conn, settings, "cli"), indent=2))
    elif args.cmd == "status":
        print(json.dumps(get_status(conn, settings), indent=2))
    elif args.cmd == "schedule":
        t = utcnow()
        for _ in range(6):
            t = next_slot(t)
            print(t.astimezone(NY).strftime("%a %Y-%m-%d %H:%M %Z"), "|", t.strftime("%Y-%m-%dT%H:%MZ"))


if __name__ == "__main__":
    main()
