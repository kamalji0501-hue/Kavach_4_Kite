#!/usr/bin/env python3
"""Batman Phase 1 supervisor CLI — reliable start/stop without .bat lock chains."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bot_lifecycle import reconcile_all
from core.bot_process_status import PHASE1_BOTS, classify_bot, format_status_line
from core.bot_supervisor import start_all_bots, stop_all_bots
from core.launcher_session_log import LauncherSessionLogger
from core.win_popup import show_error_popup, show_info_popup


def cmd_status() -> int:
    print("=== Batman supervisor — bot status ===\n")
    for robot in sorted(PHASE1_BOTS):
        print(format_status_line(classify_bot(robot, root=ROOT)))
        print()
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    print("=== Batman supervisor — reconcile ===\n")
    for result in reconcile_all(root=ROOT, kill_orphans=args.kill_orphans):
        print(f"{result.robot.upper()}: {result.action} -> {result.state.value}")
    print()
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    rc = stop_all_bots(root=ROOT, close_launcher_windows=not args.silent)
    if rc == 0:
        print("Supervisor stop: SUCCESS — all bots STOPPED.")
    else:
        print(f"Supervisor stop: FAILED (rc={rc})")
    return rc


def cmd_start(args: argparse.Namespace) -> int:
    log = LauncherSessionLogger(ROOT, "supervisor")
    log.info("=== Batman supervisor start ===")
    wait = max(30.0, args.wait_seconds)
    rc = start_all_bots(
        root=ROOT,
        force=args.force,
        wait_seconds=wait,
        new_console=not args.no_console,
        log=log,
    )
    if rc == 0:
        log.info("=== Batman supervisor — SUCCESS ===")
        if args.success_popup:
            show_info_popup(
                "Batman — Supervisor Start OK",
                "DRISHTI, KAVACH, and JAGRAN are RUNNING.\n\n"
                f"Logs: {log.log_path_hint()}",
            )
        return 0
    log.error("=== Batman supervisor — FAILURE (rc=%s) ===", rc)
    if not args.no_popup:
        show_error_popup(
            "Batman — Supervisor Start FAILED",
            "Bots did not all reach RUNNING.\n\n"
            "Try: Reconcile Bots.bat then supervisor stop + start.\n\n"
            f"Logs: {log.log_path_hint()}",
        )
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description="Batman Phase 1 bot supervisor")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show bot process status")

    p_recon = sub.add_parser("reconcile", help="Heal stale locks")
    p_recon.add_argument("--kill-orphans", action="store_true")

    p_stop = sub.add_parser("stop", help="Stop all bots")
    p_stop.add_argument("--silent", action="store_true")

    p_start = sub.add_parser("start", help="Stop-first then spawn all bots")
    p_start.add_argument("--force", action="store_true")
    p_start.add_argument("--wait-seconds", type=float, default=120.0)
    p_start.add_argument("--no-console", action="store_true", help="No separate CMD per bot")
    p_start.add_argument("--no-popup", action="store_true")
    p_start.add_argument("--success-popup", action="store_true")

    args = parser.parse_args()
    if args.command == "status":
        return cmd_status()
    if args.command == "reconcile":
        return cmd_reconcile(args)
    if args.command == "stop":
        return cmd_stop(args)
    if args.command == "start":
        return cmd_start(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
