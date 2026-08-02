"""Phase 1 Windows bot launcher contract (operator + start/stop .bat)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from core.bot_process_status import (
    PHASE1_BOTS,
    BotProcessStatus,
    BotRunState,
    bot_lock_path,
    classify_bot,
    format_status_line,
    remove_stale_lock,
)

ROOT = Path(__file__).resolve().parents[1]
_LAUNCH_ENV = "BATMAN_LAUNCHED_VIA_BAT"

OPERATOR_START_STOP_RULE = (
    "Phase 1 bots must be started and stopped only via Execution\\Start Bots\\ and "
    "Execution\\Stop Bots\\ — never by closing the CMD window (X) and never by ad-hoc "
    "python run_*.py from a shell (agent may use scripts\\stop_*.py / bot_status.py)."
)


def warn_if_not_launched_via_bat(bot_name: str) -> None:
    """Log when operator bypasses the approved start .bat."""
    if os.environ.get(_LAUNCH_ENV) == "1":
        return
    logging.getLogger(f"run_{bot_name.lower()}").warning(
        "%s started outside approved start .bat — %s",
        bot_name.upper(),
        OPERATOR_START_STOP_RULE,
    )


def pre_start_cleanup(robot: str, logger: logging.Logger, *, root: Path | None = None) -> None:
    """Kill orphaned run_*.py processes before single-instance lock (all Phase 1 bots)."""
    key = robot.lower()
    if key not in PHASE1_BOTS:
        raise ValueError(f"Unknown robot: {robot}")

    meta = PHASE1_BOTS[key]
    base = root or ROOT
    lock_path = bot_lock_path(key, root=base)
    name = key.upper()

    try:
        from scripts.stop_bot_common import stop_bot_instance

        rc = stop_bot_instance(
            runner_marker=meta["runner"],
            start_bat_marker=meta["start_bat"],
            lock_path=lock_path,
            bot_name=name,
            close_launcher_windows=False,
            max_retry_seconds=12.0,
        )
        if rc == 0:
            logger.info("Pre-start cleanup: no stale %s processes", name)
    except Exception as exc:
        logger.warning("Pre-start cleanup skipped: %s", exc)


def _attempt_force_stop(robot: str, *, root: Path) -> None:
    meta = PHASE1_BOTS[robot.lower()]
    from scripts.stop_bot_common import stop_bot_instance

    stop_bot_instance(
        runner_marker=meta["runner"],
        start_bat_marker=meta["start_bat"],
        lock_path=bot_lock_path(robot, root=root),
        bot_name=robot.upper(),
        close_launcher_windows=False,
        max_retry_seconds=12.0,
    )


def ensure_stopped_for_start(
    robot: str,
    *,
    root: Path | None = None,
    force: bool = False,
) -> tuple[int, BotProcessStatus]:
    """Return (exit_code, status). Exit 0 only when safe to start after stop preflight."""
    key = robot.lower()
    base = root or ROOT
    status = classify_bot(key, root=base)

    if status.state is BotRunState.GHOST_LOCK:
        remove_stale_lock(status.lock_path, runner_marker=PHASE1_BOTS[key]["runner"])
        status = classify_bot(key, root=base)

    if force and status.state is not BotRunState.STOPPED:
        _attempt_force_stop(key, root=base)
        status = classify_bot(key, root=base)
        if status.state is BotRunState.GHOST_LOCK:
            remove_stale_lock(status.lock_path, runner_marker=PHASE1_BOTS[key]["runner"])
            status = classify_bot(key, root=base)

    if status.state is BotRunState.STOPPED:
        return 0, status

    return _block_exit(status), status


def verify_stopped_after_stop(
    robot: str, *, root: Path | None = None
) -> tuple[int, BotProcessStatus]:
    """Post-stop verification (stop .bat). Exit 0 only when no run_*.py remains."""
    return ensure_stopped_for_start(robot, root=root, force=False)


def _block_exit(status: BotProcessStatus) -> int:
    if status.state is BotRunState.RUNNING:
        return 1
    return 2


def print_blocked_start_message(status: BotProcessStatus, *, file: object | None = None) -> None:
    meta = PHASE1_BOTS[status.robot]
    name = status.robot.upper()
    out = file or sys.stderr
    stop_bat = f"Execution\\Stop Bots\\stop {name.title()}.bat"
    print(f"\nSTART BLOCKED: {name} is not fully stopped.\n", file=out)
    print(format_status_line(status), file=out)
    print(file=out)
    print("Operator rule:", OPERATOR_START_STOP_RULE, file=out)
    print(f"1. Run: {stop_bat}", file=out)
    print("2. Run: Execution\\Show Bot Status.bat  (must show STOPPED)", file=out)
    print(f"3. Run: Execution\\Start Bots\\{meta['start_bat']}", file=out)
    print("Do NOT close the bot window with the X button — use the stop .bat only.\n", file=out)


def print_stop_verify_ok(status: BotProcessStatus) -> None:
    print(f"VERIFY: {status.robot.upper()} STOPPED — safe (no {status.runner_marker} processes).")


def set_launched_via_bat_env() -> None:
    os.environ[_LAUNCH_ENV] = "1"
