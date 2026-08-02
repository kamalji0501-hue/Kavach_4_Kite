#!/usr/bin/env python3
"""Preflight: bot must be STOPPED before start .bat launches run_*.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bot_launcher import (  # noqa: E402
    ensure_stopped_for_start,
    print_blocked_start_message,
    print_stop_verify_ok,
    verify_stopped_after_stop,
)
from core.bot_process_status import PHASE1_BOTS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Phase 1 bot is fully stopped.")
    parser.add_argument("robot", choices=sorted(PHASE1_BOTS))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run stop script once more before checking (start .bat recovery)",
    )
    parser.add_argument(
        "--after-stop",
        action="store_true",
        help="Post-stop verification mode (stop .bat success check)",
    )
    args = parser.parse_args()

    if args.after_stop:
        code, status = verify_stopped_after_stop(args.robot, root=ROOT)
    else:
        code, status = ensure_stopped_for_start(args.robot, root=ROOT, force=args.force)

    if code == 0:
        if args.after_stop:
            print_stop_verify_ok(status)
        return 0

    if args.after_stop:
        print(f"\nSTOP INCOMPLETE: {args.robot.upper()} still has background processes.\n")
    print_blocked_start_message(status)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
