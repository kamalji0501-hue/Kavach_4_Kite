"""Central Phase 1 bot lifecycle — reconcile, heal locks, prepare start/stop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.bot_process_status import (
    PHASE1_BOTS,
    BotRunState,
    bot_lock_path,
    classify_bot,
    remove_stale_lock,
)
from core.instance_lock import heal_stale_lock

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ReconcileResult:
    robot: str
    action: str
    state: BotRunState


def reconcile_bot(
    robot: str,
    *,
    root: Path | None = None,
    kill_orphans: bool = False,
) -> ReconcileResult:
    """Heal locks and optionally stop orphan processes for one bot."""
    base = root or ROOT
    key = robot.lower()
    meta = PHASE1_BOTS[key]
    marker = meta["runner"]
    lock_path = bot_lock_path(key, root=base)

    heal_stale_lock(lock_path, marker)
    status = classify_bot(key, root=base)

    if status.state is BotRunState.GHOST_LOCK:
        remove_stale_lock(lock_path, runner_marker=marker)
        status = classify_bot(key, root=base)
        return ReconcileResult(key, "removed ghost lock", status.state)

    if status.state is BotRunState.STOPPED:
        return ReconcileResult(key, "already stopped", status.state)

    if status.state is BotRunState.RUNNING:
        return ReconcileResult(key, "running (ok)", status.state)

    if status.pids and kill_orphans:
        from scripts.stop_bot_common import stop_bot_instance

        stop_bot_instance(
            runner_marker=marker,
            start_bat_marker=meta["start_bat"],
            lock_path=lock_path,
            bot_name=key.upper(),
            close_launcher_windows=False,
            max_retry_seconds=15.0,
        )
        heal_stale_lock(lock_path, marker)
        status = classify_bot(key, root=base)
        if status.state is BotRunState.STOPPED:
            return ReconcileResult(key, "stopped orphan process(es)", status.state)
        return ReconcileResult(key, "stop attempted (still not stopped)", status.state)

    if not status.pids:
        remove_stale_lock(lock_path, runner_marker=marker)
        status = classify_bot(key, root=base)
        return ReconcileResult(key, "removed stale lock (no process)", status.state)

    return ReconcileResult(key, "needs manual stop .bat", status.state)


def reconcile_all(
    *,
    root: Path | None = None,
    kill_orphans: bool = False,
) -> list[ReconcileResult]:
    return [
        reconcile_bot(name, root=root, kill_orphans=kill_orphans)
        for name in sorted(PHASE1_BOTS)
    ]


def all_stopped(*, root: Path | None = None) -> tuple[bool, list[str]]:
    """Return (ok, detail_lines) after auto-healing ghost locks."""
    from core.bot_process_status import format_status_line

    base = root or ROOT
    reconcile_all(root=base, kill_orphans=False)
    lines: list[str] = []
    ok = True
    for robot in sorted(PHASE1_BOTS):
        status = classify_bot(robot, root=base)
        if status.state is not BotRunState.STOPPED:
            ok = False
            lines.append(format_status_line(status))
    return ok, lines


def prepare_for_start(robot: str, *, root: Path | None = None, force: bool = False) -> BotRunState:
    """Heal locks; optionally stop orphans before a single-bot start."""
    result = reconcile_bot(robot, root=root, kill_orphans=force)
    return result.state
