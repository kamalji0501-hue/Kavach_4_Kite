#!/usr/bin/env python3
"""Agent feedback loop — diagnose, test, log scan, iterate until stable.

Usage:
  .venv\\Scripts\\python.exe scripts\\run_agent_feedback_loop.py
  .venv\\Scripts\\python.exe scripts\\run_agent_feedback_loop.py --restart drishti
  .venv\\Scripts\\python.exe scripts\\run_agent_feedback_loop.py --max-cycles 4 --no-stop-early

Report: data/analytics/feedback_loop/LATEST_RUN.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent_feedback_loop import run_feedback_loop  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent feedback loop (diagnose → test → logs)")
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=4,
        help="Max iterations (default 4, stops early on full pass)",
    )
    parser.add_argument(
        "--restart",
        action="append",
        default=[],
        metavar="BOT",
        help="Restart bot before cycle 1 (drishti, kavach, jagran, saransh)",
    )
    parser.add_argument("--skip-uat-e2e", action="store_true", help="Skip UAT E2E (faster)")
    parser.add_argument(
        "--no-stop-early",
        action="store_true",
        help="Always run all cycles even after first full pass",
    )
    args = parser.parse_args()
    bots = tuple(b.lower() for b in args.restart)
    if "drishti" in bots and "kavach" not in bots:
        bots = (*bots, "kavach")
    rc = run_feedback_loop(
        max_cycles=max(1, args.max_cycles),
        restart_bots=bots,
        skip_uat_e2e=args.skip_uat_e2e,
        stop_on_pass=not args.no_stop_early,
    )
    latest = ROOT / "data" / "analytics" / "feedback_loop" / "LATEST_RUN.md"
    print(f"\nFeedback loop finished exit={rc}")
    print(f"Report: {latest.resolve()}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
