#!/usr/bin/env python3
"""Phase 1 bulk stop with retries, daily launcher logs, and failure popup."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bot_lifecycle import all_stopped, reconcile_all
from core.bot_process_status import PHASE1_BOTS, bot_lock_path
from core.launcher_session_log import LauncherSessionLogger
from core.win_popup import show_error_popup

MAX_ATTEMPTS = 5
_RETRY_GAP_SECONDS = 2.0


def _all_stopped() -> tuple[bool, list[str]]:
    return all_stopped(root=ROOT)


def _stop_once(*, close_launcher_windows: bool, log: LauncherSessionLogger) -> bool:
    from scripts.stop_bot_common import stop_bot_instance

    script_ok = True
    for robot in sorted(PHASE1_BOTS):
        meta = PHASE1_BOTS[robot]
        name = robot.upper()
        log.info(f"Stopping {name}...")
        rc = stop_bot_instance(
            runner_marker=meta["runner"],
            start_bat_marker=meta["start_bat"],
            lock_path=bot_lock_path(robot, root=ROOT),
            bot_name=name,
            close_launcher_windows=close_launcher_windows,
        )
        if rc != 0:
            log.error(f"stop_bot_instance returned {rc} for {name}")
            script_ok = False
    return script_ok


def run_stop_all(
    *,
    silent: bool = False,
    popup_on_failure: bool = True,
    max_attempts: int = MAX_ATTEMPTS,
) -> int:
    log = LauncherSessionLogger(ROOT, "stop_all")
    log.info("=== Phase 1 Stop All Robots — session start ===")
    log.info(f"Log file: {log.log_path_hint()}")

    log.info("Pre-reconcile: heal stale locks...")
    for result in reconcile_all(root=ROOT, kill_orphans=False):
        log.info("  %s: %s", result.robot.upper(), result.action)

    close_windows = not silent
    last_detail: list[str] = []

    for attempt in range(1, max_attempts + 1):
        log.info(f"Stop attempt {attempt}/{max_attempts}")
        _stop_once(close_launcher_windows=close_windows, log=log)
        time.sleep(0.5)
        stopped, last_detail = _all_stopped()
        if stopped:
            log.info("VERIFY: All Phase 1 robots STOPPED (drishti, kavach, jagran).")
            log.info("=== Phase 1 Stop All — SUCCESS ===")
            from core.incident_tracker import resolve_domain_incident

            resolve_domain_incident(
                domain="stop_all",
                scenario="stop_all_failure",
                resolution_message="All Phase 1 bots verified STOPPED.",
            )
            return 0
        for line in last_detail:
            log.warning(line)
        if attempt < max_attempts:
            log.info("Reconcile with orphan kill before retry...")
            reconcile_all(root=ROOT, kill_orphans=True)
            log.info(f"Waiting {_RETRY_GAP_SECONDS:.0f}s before retry...")
            time.sleep(_RETRY_GAP_SECONDS)

    log.error(f"FAILED after {max_attempts} attempts — bots still not STOPPED.")
    log.info("=== Phase 1 Stop All — FAILURE ===")

    from core.incident_tracker import record_incident

    detail = "\n".join(last_detail)
    record_incident(
        domain="stop_all",
        scenario="stop_all_failure",
        title="Phase 1 Stop All failed",
        message=f"Bots not STOPPED after {max_attempts} attempts.",
        cause_hint="Run stop .bat per bot; check ORPHAN processes in Show Bot Status.",
        module="phase1_stop_all",
        context={"detail": detail[:2000]},
        notify_jagran=True,
        next_action="Execution\\Stop Bots\\Phase 1 Stop All Robots.bat",
    )
    msg = (
        "Could not stop all Phase 1 robots after "
        f"{max_attempts} tries.\n\n"
        f"{detail}\n\n"
        "Action:\n"
        "1. Run: Execution\\Stop Bots\\Phase 1 Stop All Robots.bat\n"
        "2. Or stop each: stop Drishti.bat, stop Kavach.bat, stop Jagran.bat\n"
        "3. Confirm: Execution\\Show Bot Status.bat\n\n"
        f"Logs: {log.log_path_hint()}"
    )
    if popup_on_failure:
        show_error_popup("Batman — Stop All FAILED", msg)

    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop all Phase 1 bots with retries and logging.")
    parser.add_argument(
        "--silent",
        action="store_true",
        help="No launcher-window auto-close hint; still logs and failure popup",
    )
    parser.add_argument(
        "--no-popup",
        action="store_true",
        help="Disable Windows error dialog (tests/automation)",
    )
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    args = parser.parse_args()
    return run_stop_all(
        silent=args.silent,
        popup_on_failure=not args.no_popup,
        max_attempts=max(1, args.max_attempts),
    )


if __name__ == "__main__":
    raise SystemExit(main())
