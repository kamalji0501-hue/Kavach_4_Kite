#!/usr/bin/env python3
"""Weekly incident dashboard — console summary + Excel export (all domains)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.incident_tracker import (  # noqa: E402
    INCIDENT_DOMAINS_ORDERED,
    INCIDENTS_ROOT,
    build_weekly_rollup,
    export_dashboard_xlsx,
    list_open_incidents,
)

_IST = ZoneInfo("Asia/Kolkata")


def _print_rollup(rollup: dict) -> None:
    print("=== Batman incident dashboard ===\n")
    print(f"Period: {rollup['period_start']} -> {rollup['period_end']} ({rollup['days']} days)")
    print(f"Total incident rows: {rollup['total_incidents']}")
    print(f"Open now (operator): {len(rollup['open_incidents'])}\n")

    print("--- By domain ---")
    for domain in INCIDENT_DOMAINS_ORDERED:
        count = rollup["by_domain_totals"].get(domain, 0)
        print(f"  {domain:12} {count:4} rows")
    print()

    print("--- Top repeating scenarios (max repeat_count) ---")
    for item in rollup["top_scenarios"][:25]:
        print(
            f"  {item['domain']:10} {item['scenario']:28} "
            f"events={item['event_count']:3} max_repeat={item['max_repeat_count']:2} "
            f"last={item['last_ts']}"
        )
    if not rollup["top_scenarios"]:
        print("  (none)")
    print()

    open_rows = list_open_incidents()
    if open_rows:
        print("--- Open incidents (registry) ---")
        for row in open_rows:
            print(
                f"  {row['incident_id']} repeat={row['repeat_count']} " f"since {row['first_seen']}"
            )
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Incident dashboard (weekly rollup + XLSX).")
    parser.add_argument("--days", type=int, default=7, help="Lookback days (default 7)")
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=None,
        help="Excel output path (default: data/analytics/incidents/dashboard_YYYYMMDD.xlsx)",
    )
    parser.add_argument("--no-xlsx", action="store_true", help="Console only")
    args = parser.parse_args()

    days = max(1, args.days)
    rollup = build_weekly_rollup(days=days)
    _print_rollup(rollup)

    if args.no_xlsx:
        return 0

    today = datetime.now(_IST).strftime("%Y%m%d")
    out = args.xlsx or (INCIDENTS_ROOT / f"dashboard_{today}.xlsx")
    path = export_dashboard_xlsx(out, days=days)
    print(f"Excel written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
