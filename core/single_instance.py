"""Single-instance guard for Phase 1 standalone bot launchers (Windows)."""

from __future__ import annotations

import atexit
import os
import sys
import time
from pathlib import Path

from core.instance_lock import (
    InstanceLockRecord,
    aux_lock_path,
    heal_stale_lock,
    is_live_lock,
    pid_owns_runner,
    process_alive,
    read_lock,
    remove_lock_files,
    write_lock,
)


def _kill_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    import subprocess

    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def ensure_single_instance(
    lock_path: Path,
    *,
    bot_name: str,
    runner_marker: str,
    stop_hint: str,
    reclaim_on_conflict: bool = False,
) -> None:
    """Prevent two copies of the same bot (structured lock + atomic aux lock).

    Stale locks (dead PID or Windows PID reuse) are removed automatically.
    When *reclaim_on_conflict* is True, a live same-runner instance is killed.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    aux = aux_lock_path(lock_path)

    def _release() -> None:
        remove_lock_files(lock_path)

    def _stale_aux() -> bool:
        if not aux.exists():
            return False
        try:
            old_pid = int(aux.read_text(encoding="utf-8").strip())
        except ValueError:
            return True
        if old_pid == os.getpid():
            return True
        if not process_alive(old_pid):
            return True
        return not pid_owns_runner(old_pid, runner_marker)

    def _reclaim_pid(old_pid: int) -> None:
        if not reclaim_on_conflict or old_pid <= 0 or old_pid == os.getpid():
            return
        if not process_alive(old_pid):
            _release()
            return
        if runner_marker and not pid_owns_runner(old_pid, runner_marker):
            _release()
            return
        print(
            f"RECLAIM: {bot_name} stopping prior instance PID {old_pid} before start.",
            file=sys.stderr,
        )
        _kill_pid(old_pid)
        for _ in range(8):
            if not process_alive(old_pid):
                break
            time.sleep(0.25)
        _release()

    heal_stale_lock(lock_path, runner_marker)

    record = read_lock(lock_path)
    if record is not None and record.pid != os.getpid():
        if is_live_lock(lock_path, runner_marker):
            if reclaim_on_conflict:
                _reclaim_pid(record.pid)
            else:
                print(
                    f"ERROR: {bot_name} is already running (PID {record.pid}).\n{stop_hint}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
        else:
            _release()
    elif _stale_aux():
        _release()

    try:
        fd = os.open(str(aux), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
    except FileExistsError:
        if _stale_aux():
            _release()
            fd = os.open(str(aux), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
        elif reclaim_on_conflict:
            try:
                aux_pid = int(aux.read_text(encoding="utf-8").strip())
            except ValueError:
                aux_pid = 0
            _reclaim_pid(aux_pid)
            fd = os.open(str(aux), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
        else:
            print(f"ERROR: {bot_name} is already starting in another process.", file=sys.stderr)
            raise SystemExit(1) from None

    write_lock(lock_path, InstanceLockRecord.current(runner_marker))
    atexit.register(_release)
