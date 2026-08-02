"""Structured bot instance locks — PID + runner identity (Windows-safe)."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
_LOCK_VERSION = 1


@dataclass(frozen=True)
class InstanceLockRecord:
    pid: int
    runner: str
    started_at: str
    hostname: str
    version: int = _LOCK_VERSION

    @classmethod
    def current(cls, runner: str) -> InstanceLockRecord:
        return cls(
            pid=os.getpid(),
            runner=runner,
            started_at=datetime.now(_IST).isoformat(),
            hostname=socket.gethostname(),
        )


def _find_runner_pids(runner: str) -> list[int]:
    from scripts.stop_bot_common import find_pids_by_commandline

    return sorted(set(find_pids_by_commandline(runner)))


def pid_owns_runner(pid: int, runner: str) -> bool:
    if pid <= 0 or not runner:
        return False
    return pid in _find_runner_pids(runner)


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    from scripts.stop_bot_common import process_exists

    return process_exists(pid)


def read_lock(lock_path: Path) -> InstanceLockRecord | None:
    """Read lock file — supports JSON v1 and legacy plain-PID text."""
    if not lock_path.exists():
        return None
    raw = lock_path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            return InstanceLockRecord(
                pid=int(payload["pid"]),
                runner=str(payload.get("runner") or ""),
                started_at=str(payload.get("started_at") or ""),
                hostname=str(payload.get("hostname") or ""),
                version=int(payload.get("version") or 1),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return InstanceLockRecord(
        pid=pid,
        runner="",
        started_at="",
        hostname="",
        version=0,
    )


def write_lock(lock_path: Path, record: InstanceLockRecord) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(asdict(record), indent=2) + "\n",
        encoding="utf-8",
    )


def aux_lock_path(lock_path: Path) -> Path:
    return lock_path.with_suffix(".pidlock")


def remove_lock_files(lock_path: Path) -> bool:
    """Remove main lock + aux pidlock. Returns True if anything removed."""
    removed = False
    aux = aux_lock_path(lock_path)
    if lock_path.exists():
        lock_path.unlink()
        removed = True
    try:
        aux.unlink(missing_ok=True)
        if aux.exists():
            pass
        elif removed:
            pass
    except OSError:
        pass
    return removed or not lock_path.exists()


def lock_pid(lock_path: Path) -> int | None:
    record = read_lock(lock_path)
    return record.pid if record else None


def is_stale_lock(lock_path: Path, runner: str) -> bool:
    """True when lock file should be removed (dead PID, recycled PID, or corrupt)."""
    if not lock_path.exists():
        return False
    record = read_lock(lock_path)
    if record is None:
        return True
    if not process_alive(record.pid):
        return True
    if runner and not pid_owns_runner(record.pid, runner):
        return True
    return False


def is_live_lock(lock_path: Path, runner: str) -> bool:
    record = read_lock(lock_path)
    if record is None:
        return False
    if not process_alive(record.pid):
        return False
    if runner:
        return pid_owns_runner(record.pid, runner)
    return True


def heal_stale_lock(lock_path: Path, runner: str) -> bool:
    """Remove lock when stale. Returns True if files were removed."""
    if not is_stale_lock(lock_path, runner):
        return False
    return remove_lock_files(lock_path)
