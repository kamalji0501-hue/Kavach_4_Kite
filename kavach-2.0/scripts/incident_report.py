#!/usr/bin/env python3
"""Print Phase 1 incident summary from by_domain daily CSV files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.incident_tracker import (  # noqa: E402
    INCIDENT_DOMAINS_ORDERED,
    list_open_incidents,
    summarize_domain_day,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize domain incident CSVs for today.")
    parser.add_argument("--domain", choices=list(INCIDENT_DOMAINS_ORDERED))
    parser.add_argument("--day", help="YYYY-MM-DD (default: today IST)")
    parser.add_argument("--open-only", action="store_true", help="Show open registry only")
    args = parser.parse_args()

    if args.open_only:
        print("=== Open incidents (operator_status=open) ===\n")
        for row in list_open_incidents(args.domain):
            print(
                f"  {row['incident_id']} repeat={row['repeat_count']} "
                f"last={row['last_seen']}"
            )
        return 0

    domains = [args.domain] if args.domain else list(INCIDENT_DOMAINS_ORDERED)
    print("=== Batman incident tracker summary ===\n")
    for domain in domains:
        summary = summarize_domain_day(domain, day=args.day)
        print(f"--- {domain.upper()} ---")
        print(f"  file: {summary.get('path', '(none)')}")
        print(f"  rows: {summary.get('total', 0)}  incidents: {summary.get('incidents', 0)}")
        print(f"  open (registry): {summary.get('open_registry_count', 0)}")
        by_sc = summary.get("by_scenario") or {}
        if by_sc:
            print("  by scenario:")
            for sc, count in sorted(by_sc.items(), key=lambda x: -x[1]):
                print(f"    {sc}: {count}")
        print()
    print("Weekly Excel: scripts\\incident_dashboard.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
