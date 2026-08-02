#!/usr/bin/env python3
"""Show Phase 1 bot process + lock state (operator visibility)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bot_process_status import (  # noqa: E402
    PHASE1_BOTS,
    BotRunState,
    classify_bot,
    exit_code_for,
    format_status_line,
    remove_stale_lock,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show whether DRISHTI/KAVACH/JAGRAN are running (detects hidden orphans)."
    )
    parser.add_argument(
        "robot",
        nargs="?",
        choices=[*PHASE1_BOTS, "all"],
        default="all",
        help="Robot name or 'all' (default)",
    )
    parser.add_argument(
        "--fix-ghost-lock",
        action="store_true",
        help="Remove lock files whose PID is no longer running (default: always heal ghost locks)",
    )
    parser.add_argument(
        "--no-heal",
        action="store_true",
        help="Report only — do not auto-remove ghost/stale locks",
    )
    args = parser.parse_args()

    if args.robot == "all":
        # Legacy kavach is a past project — Phase 1 status shows kavach2 only.
        robots = [
            name
            for name, meta in sorted(PHASE1_BOTS.items())
            if not meta.get("legacy")
        ]
    else:
        robots = [args.robot]
    statuses = []
    print("=== Batman Phase 1 — bot process status ===\n")

    for robot in robots:
        status = classify_bot(robot)
        heal = not args.no_heal or args.fix_ghost_lock
        if heal and status.state is BotRunState.GHOST_LOCK:
            if remove_stale_lock(status.lock_path, runner_marker=PHASE1_BOTS[robot]["runner"]):
                print(f"Auto-healed ghost lock for {robot.upper()}.")
                status = classify_bot(robot)
        print(format_status_line(status))
        print()
        statuses.append(status)

    codes = [exit_code_for(s) for s in statuses]
    if any(c == 2 for c in codes):
        print("Action: run Execution\\Stop Bots\\stop <Bot>.bat for any ORPHAN/GHOST line above.")
        print("Do not assume a bot is stopped until this script shows STOPPED.\n")
        return 2
    if all(s.state is BotRunState.STOPPED for s in statuses):
        print("All listed bots are stopped (no run_*.py processes).\n")
        return 1
    print("At least one bot is running in the background (see PIDs above).")
    print("Use Stop Bots .bat before starting duplicates.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
