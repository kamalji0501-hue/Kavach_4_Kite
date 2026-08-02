"""Phase 1 exclusive bot instance — scan tray, kill same-bot only, acquire lock."""

from __future__ import annotations

import logging
from pathlib import Path

from core.bot_process_status import PHASE1_BOTS, BotRunState, classify_bot, format_status_line
from core.instance_lock import heal_stale_lock
from core.single_instance import ensure_single_instance

ROOT = Path(__file__).resolve().parents[1]


def scan_phase1_bots(*, root: Path | None = None) -> dict[str, object]:
    """Return classify_bot status for every Phase 1 robot (process-tray snapshot)."""
    base = root or ROOT
    return {name: classify_bot(name, root=base) for name in PHASE1_BOTS}


def log_process_tray(logger: logging.Logger, *, root: Path | None = None) -> None:
    """Log one-line status for each Phase 1 bot before start."""
    for name, status in scan_phase1_bots(root=root).items():
        head = format_status_line(status).split("\n", 1)[0]
        logger.info("Process tray — %s: %s", name.upper(), head)


def reclaim_same_bot_instances(
    robot: str,
    lock_path: Path,
    logger: logging.Logger,
    *,
    root: Path | None = None,
    max_retry_seconds: float = 15.0,
) -> int:
    """Kill only *robot* run_*.py trees (never other bots). Returns stop_bot_instance rc."""
    key = robot.lower()
    if key not in PHASE1_BOTS:
        raise ValueError(f"Unknown robot: {robot}")

    meta = PHASE1_BOTS[key]
    name = key.upper()
    status = classify_bot(key, root=root or ROOT)
    if status.state is BotRunState.STOPPED:
        logger.info("%s reclaim: no prior instance on process tray", name)
        return 0

    logger.info(
        "%s reclaim: stopping prior instance(s) — %s",
        name,
        format_status_line(status).split("\n", 1)[0],
    )
    from scripts.stop_bot_common import stop_bot_instance

    return stop_bot_instance(
        runner_marker=meta["runner"],
        start_bat_marker=meta["start_bat"],
        lock_path=lock_path,
        bot_name=name,
        close_launcher_windows=False,
        max_retry_seconds=max_retry_seconds,
    )


def bootstrap_exclusive_bot(
    robot: str,
    lock_path: Path,
    logger: logging.Logger,
    *,
    root: Path | None = None,
) -> None:
    """Scan tray, kill same-bot duplicates, then acquire single-instance lock."""
    log_process_tray(logger, root=root)
    rc = reclaim_same_bot_instances(robot, lock_path, logger, root=root)
    if rc != 0:
        logger.warning(
            "%s reclaim: stop returned %s — attempting lock anyway",
            robot.upper(),
            rc,
        )
    meta = PHASE1_BOTS[robot.lower()]
    heal_stale_lock(lock_path, meta["runner"])
    ensure_single_instance(
        lock_path,
        bot_name=robot.upper(),
        runner_marker=meta["runner"],
        stop_hint=f"Run: Execution\\Stop Bots\\{meta['start_bat'].replace('start ', 'stop ')}",
        reclaim_on_conflict=True,
    )
