#!/usr/bin/env python3
"""Delete old runtime log day folders older than N days (default 30)."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prune_runtime_logs(*, root: Path, keep_days: int, dry_run: bool) -> int:
    runtime = root / "logs" / "runtime"
    if not runtime.exists():
        return 0

    cutoff = datetime.now().date() - timedelta(days=keep_days)
    removed = 0

    for ym_dir in runtime.iterdir():
        if not ym_dir.is_dir():
            continue
        for day_dir in ym_dir.iterdir():
            if not day_dir.is_dir():
                continue
            try:
                day = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day >= cutoff:
                continue
            if dry_run:
                print(f"would remove: {day_dir}")
            else:
                shutil.rmtree(day_dir, ignore_errors=True)
                print(f"removed: {day_dir}")
            removed += 1

    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune old logs/runtime day folders")
    parser.add_argument("--days", type=int, default=30, help="Keep last N calendar days")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    n = prune_runtime_logs(root=ROOT, keep_days=args.days, dry_run=args.dry_run)
    print(f"{'Would remove' if args.dry_run else 'Removed'} {n} day folder(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
