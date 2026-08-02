#!/usr/bin/env python3
"""Close open incidents in the operator registry (writes RECOVERED + closed CSV row)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.incident_tracker import (  # noqa: E402
    INCIDENT_DOMAINS_ORDERED,
    close_incident,
    list_open_incidents,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Close open domain incidents.")
    parser.add_argument(
        "--incident-id",
        help="Full id, e.g. kavach::log_error",
    )
    parser.add_argument("--domain", choices=list(INCIDENT_DOMAINS_ORDERED))
    parser.add_argument("--scenario", help="Scenario name (with --domain)")
    parser.add_argument("--note", default="Closed by operator", help="Recovery message")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List open incidents and exit",
    )
    args = parser.parse_args()

    if args.list:
        rows = list_open_incidents(args.domain)
        if not rows:
            print("No open incidents.")
            return 0
        print("Open incidents:\n")
        for row in rows:
            print(
                f"  {row['incident_id']}  repeat={row['repeat_count']}  "
                f"last={row['last_seen']}"
            )
        return 0

    if not args.incident_id and not (args.domain and args.scenario):
        parser.error("Use --incident-id OR both --domain and --scenario (or --list)")
        return 2

    ok = close_incident(
        incident_id=args.incident_id,
        domain=args.domain,
        scenario=args.scenario,
        note=args.note,
    )
    if not ok:
        print("No matching open incident (already closed or unknown id).", file=sys.stderr)
        return 1
    target = args.incident_id or f"{args.domain}::{args.scenario}"
    print(f"Closed: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
