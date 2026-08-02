#!/usr/bin/env python3

"""Diagnose a Batman robot: process, locks, logs, cache. Agent/operator tool."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:

    sys.path.insert(0, str(ROOT))


from core.batman_mode import get_mode, log_runtime_root, nifty_ltp_cache_path  # noqa: E402
from core.bot_process_status import (  # noqa: E402
    PHASE1_BOTS,
    BotRunState,
    classify_bot,
    exit_code_for,
    format_status_line,
    remove_stale_lock,
)

_IST = ZoneInfo("Asia/Kolkata")


_ROBOTS = ("drishti", "kavach", "jagran")


def _day_root(when: datetime | None = None) -> Path:

    ts = when or datetime.now(_IST)

    return log_runtime_root(ROOT) / ts.strftime("%Y-%m") / ts.strftime("%Y-%m-%d")


def _tail(path: Path, n: int = 15) -> list[str]:

    if not path.exists():

        return []

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    return lines[-n:]


def _error_hits(lines: list[str]) -> list[str]:

    keys = ("ERROR", "CRITICAL", "Traceback", "429", "failed after 3", "crashed")

    return [ln for ln in lines if any(k in ln for k in keys)]


def _log_display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def diagnose(robot: str, *, date: str | None = None, fix_ghost_lock: bool = False) -> int:

    robot = robot.lower()

    if robot not in _ROBOTS:

        print(f"Unknown robot: {robot}. Use: {', '.join(_ROBOTS)}")

        return 2

    when = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=_IST) if date else datetime.now(_IST)

    day = _day_root(when)

    mode = get_mode(ROOT)
    print(f"=== Diagnose {robot.upper()} ({when.strftime('%Y-%m-%d')} IST, mode={mode}) ===\n")

    status = classify_bot(robot, root=ROOT)

    if fix_ghost_lock and status.state is BotRunState.GHOST_LOCK:

        if remove_stale_lock(
            status.lock_path,
            runner_marker=PHASE1_BOTS[robot.lower()]["runner"],
        ):

            print("Removed stale lock file.\n")

            status = classify_bot(robot, root=ROOT)

    print(format_status_line(status))

    print()

    all_log = day / robot / "logs" / "all.log"

    err_log = day / robot / "errors" / "all_errors.log"

    print(
        f"All log:  {_log_display(all_log)} ({all_log.stat().st_size if all_log.exists() else 0} B)"
    )

    print(
        f"Err log:  {_log_display(err_log)} ({err_log.stat().st_size if err_log.exists() else 0} B)"
    )

    err_lines = _tail(err_log, 20) if err_log.exists() else []

    if err_lines:

        print("\n--- all_errors.log (last 20) ---")

        for ln in err_lines:

            print(ln[:240])

    tail = _tail(all_log, 40)

    hits = _error_hits(tail)

    if hits:

        print("\n--- recent ERROR lines in all.log ---")

        for ln in hits[-10:]:

            print(ln[:240])

    if robot == "drishti":

        cache = nifty_ltp_cache_path(ROOT)

        if cache.exists():

            data = json.loads(cache.read_text(encoding="utf-8"))

            print(f"\nNIFTY cache LTP: {data.get('ltp')} updated: {data.get('updated_at')}")

    if robot == "kavach":

        cache = nifty_ltp_cache_path(ROOT)

        if cache.exists():

            data = json.loads(cache.read_text(encoding="utf-8"))

            print(
                "\nNote: KAVACH ATO needs fresh DRISHTI LTP cache during market hours. "
                f"Cache updated_at={data.get('updated_at')}"
            )

    print("\n--- suggested actions ---")

    if status.state is BotRunState.STOPPED:

        print(f"  Start: .venv\\Scripts\\python.exe {status.runner_marker}")

        print(f"  Or: Execution\\Start Bots\\start {robot.title()}.bat")

    elif status.state in (BotRunState.ORPHAN, BotRunState.GHOST_LOCK):

        print("  Run stop script even if you already closed the window:")

        print(f"  Execution\\Stop Bots\\stop {robot.title()}.bat")

        print("  Then: .venv\\Scripts\\python.exe scripts\\bot_status.py all")

    if robot == "kavach" and err_lines and "LTP" in "\n".join(err_lines):

        print("  Ensure DRISHTI is running and NIFTY feed is active (market hours).")

        print("  Off-hours stale LTP ERROR on ATO startup scan is expected; monitoring continues.")

    return exit_code_for(status)


def main() -> int:

    parser = argparse.ArgumentParser(description="Diagnose Batman robot logs and process")

    parser.add_argument("robot", choices=_ROBOTS)

    parser.add_argument("--date", help="YYYY-MM-DD (default: today IST)")

    parser.add_argument(
        "--fix-ghost-lock",
        action="store_true",
        help="Remove lock file when its PID is no longer running",
    )

    args = parser.parse_args()

    return diagnose(args.robot, date=args.date, fix_ghost_lock=args.fix_ghost_lock)


if __name__ == "__main__":

    sys.exit(main())
