"""Windows Phase 1 bot process + lock visibility (no secrets)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from core.instance_lock import lock_pid

ROOT = Path(__file__).resolve().parents[1]

PHASE1_BOTS: dict[str, dict[str, str]] = {
    "drishti": {
        "runner": "run_drishti.py",
        "lock": "drishti.lock",
        "start_bat": "start Drishti.bat",
        "stop_script": "scripts\\stop_drishti.py",
    },
    "kavach": {
        "runner": "run_kavach2.py",
        "lock": "kavach.lock",
        "start_bat": "start Kavach.bat",
        "stop_script": "scripts\\stop_kavach.py",
        # Legacy Kavach — kept on disk; Phase 1 testing uses kavach2 instead.
        "legacy": True,
    },
    "kavach2": {
        "runner": "run_kavach2.py",
        "lock": "kavach2.lock",
        "start_bat": "start Kavach2.bat",
        "stop_script": "scripts\\stop_kavach2.py",
    },
    "jagran": {
        "runner": "run_jagran.py",
        "lock": "jagran.lock",
        "start_bat": "start Jagran.bat",
        "stop_script": "scripts\\stop_jagran.py",
    },
    "saransh": {
        "runner": "run_saransh.py",
        "lock": "saransh.lock",
        "start_bat": "start Saransh.bat",
        "stop_script": "scripts\\stop_saransh.py",
        "optional": True,
    },
    "ratripal": {
        "runner": "run_ratripal.py",
        "lock": "ratripal.lock",
        "start_bat": "start Ratripal.bat",
        "stop_script": "scripts\\stop_ratripal.py",
        "optional": True,
    },
}

# Active Phase 1 stack for start/verify (legacy kavach excluded).
PHASE1_CORE_BOTS: tuple[str, ...] = ("drishti", "kavach2", "jagran")
PHASE1_OPTIONAL_BOTS: tuple[str, ...] = ("saransh",)


class BotRunState(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    ORPHAN = "orphan"
    GHOST_LOCK = "ghost_lock"


@dataclass(frozen=True)
class BotProcessStatus:
    robot: str
    runner_marker: str
    lock_path: Path
    pids: tuple[int, ...]
    lock_pid: int | None
    state: BotRunState
    warnings: tuple[str, ...]

    @property
    def instance_count(self) -> int:
        """Best-effort count of launcher trees (venv parent + worker child = 1)."""
        if not self.pids:
            return 0
        try:
            from scripts.stop_bot_common import get_parent_pid
        except Exception:
            return len(self.pids)

        roots = set(self.pids)
        for pid in self.pids:
            parent = get_parent_pid(pid)
            if parent is not None and parent in roots:
                roots.discard(pid)
        return len(roots)


def _find_pids(marker: str) -> list[int]:
    from scripts.stop_bot_common import find_pids_by_commandline

    return sorted(set(find_pids_by_commandline(marker)))


def _read_lock_pid(lock_path: Path) -> int | None:
    return lock_pid(lock_path)


def _lock_pid_alive(lock_pid: int | None) -> bool:
    if lock_pid is None:
        return False
    from scripts.stop_bot_common import process_exists

    return process_exists(lock_pid)


def _lock_pid_owns_runner(lock_pid: int | None, marker: str) -> bool:
    if lock_pid is None:
        return False
    return lock_pid in _find_pids(marker)


def bot_lock_path(robot: str, *, root: Path | None = None) -> Path:
    """Mode-aware lock file path (must match run_*.py single-instance guard)."""
    key = robot.lower()
    if key not in PHASE1_BOTS:
        raise ValueError(f"Unknown robot: {robot}")
    from core.batman_mode import bot_lock_path as resolve_bot_lock

    return resolve_bot_lock(key, root or ROOT)


def classify_bot(robot: str, *, root: Path | None = None) -> BotProcessStatus:
    key = robot.lower()
    if key not in PHASE1_BOTS:
        raise ValueError(f"Unknown robot: {robot}")

    meta = PHASE1_BOTS[key]
    base = root or ROOT
    marker = meta["runner"]
    lock_path = bot_lock_path(key, root=base)
    pids = tuple(_find_pids(marker))
    lock_pid = _read_lock_pid(lock_path)
    lock_alive = _lock_pid_alive(lock_pid)
    warnings: list[str] = []

    if pids:
        if lock_pid is None:
            state = BotRunState.ORPHAN
            stop_bat = meta["start_bat"].replace("start ", "stop ")
            warnings.append(
                "Process is running but lock file is missing — stop may have been skipped "
                f"or the launcher window was closed with X instead of Stop Bots\\{stop_bat}."
            )
        elif lock_pid not in pids:
            if lock_alive:
                state = BotRunState.ORPHAN
                warnings.append(
                    f"Lock PID {lock_pid} is alive but not in the run_{key}.py process list — "
                    "possible duplicate or wrong lock."
                )
            else:
                state = BotRunState.RUNNING
                warnings.append(
                    f"Stale lock file (PID {lock_pid} is not running). "
                    "Bot is still active in the background."
                )
        else:
            state = BotRunState.RUNNING
        if len(pids) > 2:
            warnings.append(
                f"More than one launcher tree detected ({len(pids)} PIDs) — "
                "run the stop script before starting again."
            )
    elif lock_pid is not None:
        if lock_alive and _lock_pid_owns_runner(lock_pid, marker):
            state = BotRunState.ORPHAN
            warnings.append(
                f"Lock says PID {lock_pid} is running but no {marker} process was found."
            )
        else:
            state = BotRunState.GHOST_LOCK
            if lock_alive:
                warnings.append(
                    f"Lock PID {lock_pid} is alive but not {marker} "
                    "(Windows PID reuse). Safe to delete lock or run stop script."
                )
            else:
                warnings.append(
                    f"Lock file lists dead PID {lock_pid}. Safe to delete lock or run stop script."
                )
    else:
        state = BotRunState.STOPPED

    from core.bot_health import health_age_seconds, health_confirms_running, read_bot_health

    health = read_bot_health(base, key)
    health_age = health_age_seconds(health) if health else None
    confirmed, _ = health_confirms_running(base, key, pids)

    if confirmed and state is not BotRunState.RUNNING:
        refreshed = tuple(_find_pids(marker))
        if refreshed:
            pids = refreshed
            state = BotRunState.RUNNING
            if lock_pid is None:
                warnings = [
                    w
                    for w in warnings
                    if "lock file is missing" not in w
                ]
    elif state is BotRunState.RUNNING and health is not None and health_age is not None:
        if health_age > 180.0:
            warnings.append(
                f"health heartbeat stale ({health_age:.0f}s) — verify {marker} is responsive"
            )
        elif (
            str(health.get("status", "")).lower() != "running"
            and health_age <= 90.0
        ):
            warnings.append(
                f"health.json reports status={health.get('status')!r} while process list shows RUNNING"
            )
    elif not pids and health is not None and health_age is not None and health_age <= 90.0:
        if str(health.get("status", "")).lower() == "running":
            refreshed = tuple(_find_pids(marker))
            if refreshed:
                pids = refreshed
                state = BotRunState.RUNNING

    return BotProcessStatus(
        robot=key,
        runner_marker=marker,
        lock_path=lock_path,
        pids=pids,
        lock_pid=lock_pid,
        state=state,
        warnings=tuple(warnings),
    )


def format_status_line(status: BotProcessStatus) -> str:
    import sys

    meta = PHASE1_BOTS[status.robot]
    name = status.robot.upper()
    if status.state is BotRunState.RUNNING:
        pid_text = ",".join(str(p) for p in status.pids)
        hint = ""
        if sys.platform == "win32" and status.instance_count == 1 and len(status.pids) == 2:
            hint = " — CMD launcher + Python worker (normal on dev laptop)"
        head = f"{name}: RUNNING ({status.instance_count} instance, PIDs {pid_text}{hint})"
    elif status.state is BotRunState.STOPPED:
        head = f"{name}: STOPPED (no background process)"
    elif status.state is BotRunState.ORPHAN:
        pid_text = ",".join(str(p) for p in status.pids) or "(none)"
        head = f"{name}: ORPHAN / UNEXPECTED — PIDs {pid_text}"
    else:
        head = f"{name}: GHOST LOCK (file {meta['lock']}, PID {status.lock_pid} dead)"

    lines = [head]
    if status.lock_pid is not None:
        lines.append(f"  lock: {status.lock_path.name} -> PID {status.lock_pid}")
    for w in status.warnings:
        lines.append(f"  WARNING: {w}")
    if status.state is not BotRunState.STOPPED:
        if sys.platform == "win32":
            lines.append(f"  stop: .venv\\Scripts\\python.exe {meta['stop_script']}")
        else:
            stop_script = meta["stop_script"].replace("\\", "/")
            lines.append(f"  stop: .venv/bin/python {stop_script}")
    else:
        if sys.platform == "win32":
            lines.append(f"  start: Execution\\Start Bots\\{meta['start_bat']}")
        else:
            start_sh = meta["start_bat"].replace(".bat", ".sh")
            lines.append(f"  start: Execution/Start Bots/{start_sh}")
    return "\n".join(lines)


def remove_stale_lock(lock_path: Path, *, runner_marker: str | None = None) -> bool:
    """Remove lock when PID is dead or no longer owns the bot runner.

    Returns True if a file was removed.
    """
    lock_pid = _read_lock_pid(lock_path)
    if lock_pid is None and not lock_path.exists():
        return False
    if lock_pid is not None and _lock_pid_alive(lock_pid):
        if runner_marker and _lock_pid_owns_runner(lock_pid, runner_marker):
            return False
        if runner_marker is None:
            return False
    aux = lock_path.with_suffix(".pidlock")
    removed = False
    if lock_path.exists():
        lock_path.unlink()
        removed = True
    try:
        aux.unlink(missing_ok=True)
    except OSError:
        pass
    return removed


def heal_bot_lock(lock_path: Path, runner_marker: str) -> bool:
    """Remove lock files when stale (delegates to instance_lock + aux cleanup)."""
    from core.instance_lock import heal_stale_lock

    if heal_stale_lock(lock_path, runner_marker):
        return True
    return remove_stale_lock(lock_path, runner_marker=runner_marker)


def exit_code_for(status: BotProcessStatus) -> int:
    if status.state is BotRunState.RUNNING:
        return 0
    if status.state is BotRunState.STOPPED:
        return 1
    return 2
