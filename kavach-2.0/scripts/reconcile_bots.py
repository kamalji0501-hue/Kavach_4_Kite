#!/usr/bin/env python3
"""Auto-heal Phase 1 bot locks and orphans — run before Start All when stuck."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bot_lifecycle import reconcile_all, reconcile_bot  # noqa: E402
from core.bot_process_status import (  # noqa: E402
    PHASE1_BOTS,
    BotRunState,
    classify_bot,
    format_status_line,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Heal stale locks and reconcile Phase 1 bot process state."
    )
    parser.add_argument(
        "robot",
        nargs="?",
        choices=[*PHASE1_BOTS, "all"],
        default="all",
        help="Robot name or 'all' (default)",
    )
    parser.add_argument(
        "--kill-orphans",
        action="store_true",
        help="Stop background run_*.py processes classified as ORPHAN",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print summary line per bot",
    )
    args = parser.parse_args()

    print("=== Batman reconcile bots ===\n")

    worst = 0
    if args.robot == "all":
        results = reconcile_all(root=ROOT, kill_orphans=args.kill_orphans)
    else:
        results = [reconcile_bot(args.robot, root=ROOT, kill_orphans=args.kill_orphans)]

    for result in results:
        name = result.robot.upper()
        if result.state in (BotRunState.STOPPED, BotRunState.RUNNING):
            code = 0
        else:
            code = 2
            worst = 2
        if args.quiet:
            print(f"{name}: {result.action} -> {result.state.value}")
        else:
            status = classify_bot(result.robot, root=ROOT)
            print(f"{name}: {result.action}")
            print(format_status_line(status))
            print()
        if code == 2:
            pass

    if worst == 0:
        print("Reconcile complete — safe to Start All or check Show Bot Status.\n")
        return 0

    print("Some bots still need stop .bat — see lines above.\n")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
