#!/usr/bin/env python3
"""Validate single-root log layout under logs/runtime/."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
_IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    month = datetime.now(_IST).strftime("%Y-%m")
    day_root = ROOT / "logs" / "runtime" / month / today

    print("=== Log layout validation (runtime-only) ===\n")
    ok = 0
    fail = 0

    if (ROOT / "logs" / "bots").exists():
        print(f"  [FAIL] legacy logs/bots/ still exists")
        fail += 1
    else:
        print("  [PASS] no logs/bots/ folder")
        ok += 1

    main_all = day_root / "logs" / "all.log"
    if main_all.exists() and main_all.stat().st_size > 0:
        print(f"  [PASS] main all.log ({main_all.stat().st_size} B)")
        ok += 1
    elif (day_root / "logs").exists() and list((day_root / "logs").glob("runtime_*.log")):
        print("  [PASS] main runtime window logs present (all.log not yet written)")
        ok += 1
    else:
        print("  [INFO] no main logs yet today — start a bot to create")
        ok += 1

    for bot in ("drishti", "kavach", "jagran"):
        all_log = day_root / bot / "logs" / "all.log"
        err_log = day_root / bot / "errors" / "all_errors.log"
        if all_log.exists():
            print(f"  [PASS] {bot}/logs/all.log ({all_log.stat().st_size} B)")
            ok += 1
        else:
            print(f"  [INFO] {bot}/logs/all.log not yet created")
            ok += 1
        if err_log.exists() and err_log.stat().st_size > 0:
            print(f"  [PASS] {bot}/errors/all_errors.log ({err_log.stat().st_size} B)")
            ok += 1
        elif err_log.exists():
            print(f"  [INFO] {bot}/errors/all_errors.log empty (no errors)")
            ok += 1
        else:
            print(f"  [INFO] {bot}/errors/all_errors.log not yet created")
            ok += 1

    orphans = [
        p.name
        for p in (day_root / "logs").glob("*.log")
        if (day_root / "logs").exists()
        and not p.name.startswith("runtime_")
        and p.name != "all.log"
        and not p.name.startswith("runtime_legacy")
    ]
    if orphans:
        print(f"  [FAIL] orphan files in day/logs/: {orphans}")
        fail += 1
    else:
        print("  [PASS] day/logs/ clean")
        ok += 1

    print(f"\n=== Result: {ok} passed, {fail} failed ===")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
