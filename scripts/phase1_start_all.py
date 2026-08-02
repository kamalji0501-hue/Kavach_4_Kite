#!/usr/bin/env python3
"""Phase 1 bulk start: stop-first, launch windows, wait up to 2 min, verify RUNNING."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bot_process_status import PHASE1_BOTS, BotRunState, classify_bot, format_status_line
from core.launcher_session_log import LauncherSessionLogger
from core.startup_gates import wait_bot_running, wait_drishti_ltp_ready
from core.win_popup import show_error_popup, show_info_popup

START_ORDER = ("drishti", "kavach2", "jagran")
OPTIONAL_START_ORDER = ("saransh",)
DEFAULT_WAIT_SECONDS = 120
POLL_INTERVAL_SECONDS = 5.0
_DRISHTI_DELAY = 12.0
_KAVACH_DELAY = 5.0


def _running_report() -> tuple[bool, list[str]]:
    bad: list[str] = []
    for robot in START_ORDER:
        status = classify_bot(robot, root=ROOT)
        if status.state is BotRunState.RUNNING:
            continue
        bad.append(format_status_line(status))
    return len(bad) == 0, bad


def _launch_bot(robot: str, *, force: bool) -> None:
    import sys

    meta = PHASE1_BOTS[robot]
    start_dir = ROOT / "Execution" / "Start Bots"
    bat = start_dir / meta["start_bat"]
    sh = start_dir / meta["start_bat"].replace(".bat", ".sh")
    if sys.platform != "win32" and sh.is_file():
        args = ["bash", str(sh)]
        if force:
            args.append("force")
        subprocess.Popen(
            args,
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    title = f"{robot.upper()} Bot - Running"
    args = f'"{bat}"'
    if force:
        args += " force"
    cmd = f'start "{title}" cmd /k call {args}'
    subprocess.run(cmd, cwd=ROOT, shell=True, check=False)


def run_start_all(
    *,
    force: bool = False,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    popup_on_failure: bool = True,
    popup_on_success: bool = False,
    use_supervisor: bool = True,
) -> int:
    log = LauncherSessionLogger(ROOT, "start_all")
    log.info("=== Phase 1 Start All Robots — session start ===")
    log.info(f"Log file: {log.log_path_hint()}")

    if use_supervisor:
        log.info("Mode: supervisor (direct Python spawn — recommended)")
        from core.bot_supervisor import start_all_bots

        wait = max(30.0, wait_seconds)
        try:
            from core.batman_mode import get_mode, workspace_root

            if get_mode(workspace_root(ROOT)) == "uat" and wait_seconds == DEFAULT_WAIT_SECONDS:
                wait = 180.0
        except Exception:
            pass
        rc = start_all_bots(root=ROOT, force=force or True, wait_seconds=wait, log=log)
        if rc == 0:
            log.info("=== Phase 1 Start All — SUCCESS (supervisor) ===")
            try:
                from scripts.phase1_post_start_verify import run_verify

                run_verify(require_ltp=False)
            except Exception as exc:
                log.warning("Post-start verify skipped: %s", exc)
            if popup_on_success:
                show_info_popup(
                    "Batman — Start All OK",
                    "DRISHTI, KAVACH 2.0, and JAGRAN are RUNNING.\n\n"
                    f"Logs: {log.log_path_hint()}",
                )
            return 0
        log.error("=== Phase 1 Start All — FAILURE (supervisor rc=%s) ===", rc)
        if popup_on_failure:
            show_error_popup(
                "Batman — Start All FAILED",
                "Supervisor could not start all bots.\n\n"
                "Run: Execution\\Start Bots\\Reconcile Bots.bat\n\n"
                f"Logs: {log.log_path_hint()}",
            )
        return rc if rc else 2

    log.info(
        "Mode: legacy .bat launchers"
    )
    log.info(
        "Robots may take up to "
        f"{int(wait_seconds)}s to show RUNNING — polling every {int(POLL_INTERVAL_SECONDS)}s."
    )

    from scripts.phase1_stop_all import run_stop_all

    log.info("Step 0: Reconcile stale locks...")
    try:
        from core.bot_lifecycle import reconcile_all

        for result in reconcile_all(root=ROOT, kill_orphans=False):
            log.info("  %s: %s", result.robot.upper(), result.action)
    except Exception as exc:
        log.warning("Reconcile skipped: %s", exc)

    log.info("Step 1: Stop all (clean slate)...")
    stop_rc = run_stop_all(silent=True, popup_on_failure=popup_on_failure)
    if stop_rc != 0:
        log.error("Aborting start — stop-all did not reach STOPPED.")
        from core.incident_tracker import record_incident

        record_incident(
            domain="start_all",
            scenario="start_all_abort",
            title="Start All aborted",
            message="Stop-all did not reach STOPPED before launch.",
            cause_hint="Run Phase 1 Stop All Robots.bat and verify STOPPED.",
            module="phase1_start_all",
            notify_jagran=True,
        )
        if popup_on_failure:
            show_error_popup(
                "Batman — Start All ABORTED",
                "Could not stop existing bots before start.\n\n"
                "Run: Execution\\Stop Bots\\Phase 1 Stop All Robots.bat\n\n"
                f"Logs: {log.log_path_hint()}",
            )
        return 1

    log.info(
        "Step 2: Sequential launch DRISHTI -> KAVACH2 -> JAGRAN"
        " (+ optional SARANSH last if enabled + token + start bat)..."
    )

    _launch_bot("drishti", force=force or True)
    log.info("Gate: waiting for DRISHTI RUNNING + NIFTY LTP cache...")
    if not wait_bot_running("drishti", timeout_seconds=wait_seconds * 0.5, root=ROOT):
        log.error("DRISHTI did not reach RUNNING before KAVACH2 launch.")
    ltp_ok, ltp_detail = wait_drishti_ltp_ready(timeout_seconds=90.0, root=ROOT)
    log.info("DRISHTI LTP gate: %s (%s)", "OK" if ltp_ok else "WARN", ltp_detail)
    if not ltp_ok:
        log.warning("Proceeding to KAVACH2 — LTP gate not satisfied (may be off-hours).")

    _launch_bot("kavach2", force=force or True)
    log.info("Gate: waiting for KAVACH 2.0 RUNNING...")
    if not wait_bot_running("kavach2", timeout_seconds=60.0, root=ROOT):
        log.warning("KAVACH 2.0 not RUNNING yet — JAGRAN launch continues after short delay.")
    time.sleep(_KAVACH_DELAY)

    _launch_bot("jagran", force=force or True)
    log.info("Gate: waiting for JAGRAN RUNNING...")
    wait_bot_running("jagran", timeout_seconds=45.0, root=ROOT)

    from core.optional_bot_startup import optional_bot_enabled

    for optional_bot in OPTIONAL_START_ORDER:
        ok, reason = optional_bot_enabled(optional_bot, root=ROOT)
        if not ok:
            log.info("Optional %s skipped: %s", optional_bot.upper(), reason)
            continue
        log.info("Step 2b: Launch optional %s (after JAGRAN)...", optional_bot.upper())
        _launch_bot(optional_bot, force=force or True)
        wait_bot_running(optional_bot, timeout_seconds=45.0, root=ROOT)

    log.info("Step 3: Waiting for all bots to report RUNNING...")
    deadline = time.monotonic() + wait_seconds
    poll = 0
    last_bad: list[str] = []
    while time.monotonic() < deadline:
        poll += 1
        ok, last_bad = _running_report()
        elapsed = int(wait_seconds - max(0, deadline - time.monotonic()))
        if ok:
            log.info(f"VERIFY: All Phase 1 robots RUNNING after ~{elapsed}s (poll {poll}).")
            for robot in START_ORDER:
                st = classify_bot(robot, root=ROOT)
                log.info(f"  {robot.upper()}: PIDs {','.join(map(str, st.pids)) or 'none'}")
            log.info("Step 4: Post-start verify...")
            try:
                from scripts.phase1_post_start_verify import run_verify

                verify_rc = run_verify(require_ltp=False)
                if verify_rc != 0:
                    log.warning("Post-start verify reported issues (see stdout above).")
            except Exception as exc:
                log.warning("Post-start verify skipped: %s", exc)

            log.info("=== Phase 1 Start All — SUCCESS ===")
            from core.incident_tracker import resolve_domain_incident

            for scenario in ("start_all_timeout", "start_all_abort"):
                resolve_domain_incident(
                    domain="start_all",
                    scenario=scenario,
                    resolution_message="All Phase 1 bots verified RUNNING.",
                )
            if popup_on_success:
                show_info_popup(
                    "Batman — Start All OK",
                    "DRISHTI, KAVACH 2.0, and JAGRAN are RUNNING.\n\n"
                    "Check the three CMD windows.\n"
                    f"Logs: {log.log_path_hint()}",
                )
            return 0
        log.info(f"Poll {poll} @ ~{elapsed}s — not all RUNNING yet.")
        for line in last_bad:
            log.info(f"  {line.split(chr(10))[0]}")
        time.sleep(POLL_INTERVAL_SECONDS)

    log.error(f"TIMEOUT after {int(wait_seconds)}s — not all bots RUNNING.")
    for line in last_bad:
        log.error(line)
    log.info("=== Phase 1 Start All — FAILURE ===")

    from core.incident_tracker import record_incident

    detail = "\n".join(last_bad)
    record_incident(
        domain="start_all",
        scenario="start_all_timeout",
        title="Phase 1 Start All timeout",
        message=f"Not all bots RUNNING within {int(wait_seconds)}s.",
        cause_hint="Check bot CMD windows; bots may still be starting.",
        module="phase1_start_all",
        context={"detail": detail[:2000], "wait_seconds": int(wait_seconds)},
        notify_jagran=True,
        next_action="Show Bot Status.bat; retry Start All after Stop All.",
    )
    msg = (
        f"Not all Phase 1 robots reached RUNNING within {int(wait_seconds)} seconds.\n\n"
        f"{detail}\n\n"
        "Bots may still be starting in their windows — check each CMD title.\n"
        "If stuck:\n"
        "1. Execution\\Stop Bots\\Phase 1 Stop All Robots.bat\n"
        "2. Fix issues, then Start All again\n\n"
        f"Logs: {log.log_path_hint()}"
    )
    if popup_on_failure:
        show_error_popup("Batman — Start All FAILED", msg)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Start all Phase 1 bots with verification.")
    parser.add_argument("--force", action="store_true", help="Pass force to each start .bat")
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help="Max wait for all RUNNING (default 120)",
    )
    parser.add_argument("--no-popup", action="store_true", help="Disable Windows dialogs")
    parser.add_argument(
        "--success-popup",
        action="store_true",
        help="Show info dialog when all bots are RUNNING",
    )
    parser.add_argument(
        "--legacy-bats",
        action="store_true",
        help="Use legacy start .bat windows instead of supervisor spawn",
    )
    args = parser.parse_args()
    wait = max(30.0, args.wait_seconds)
    try:
        from core.batman_mode import get_mode, workspace_root

        if get_mode(workspace_root(ROOT)) == "uat" and args.wait_seconds == DEFAULT_WAIT_SECONDS:
            wait = 180.0
    except Exception:
        pass
    return run_start_all(
        force=args.force,
        wait_seconds=wait,
        popup_on_failure=not args.no_popup,
        popup_on_success=args.success_popup,
        use_supervisor=not args.legacy_bats,
    )


if __name__ == "__main__":
    raise SystemExit(main())
