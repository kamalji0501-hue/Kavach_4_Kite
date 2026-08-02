"""Shared helpers for stopping standalone bot launcher windows on Windows."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import time
from pathlib import Path

import sys

POWERSHELL = (
    Path(os.environ.get("SystemRoot", r"C:\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)

DEFAULT_RETRY_SECONDS = 10.0
DEFAULT_RETRY_INTERVAL = 2.0
SILENT_RETRY_SECONDS = 10.0
SILENT_RETRY_INTERVAL = 2.0


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def kill_pid(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    else:
        try:
            os.kill(pid, 9)
            return True
        except OSError:
            return False


def _run_powershell(script: str) -> str:
    if not POWERSHELL.exists():
        return ""
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def find_pids_by_commandline(marker: str) -> list[int]:
    """Return python/py PIDs whose command line contains ``marker``."""
    if sys.platform == "win32":
        escaped = marker.replace("'", "''")
        script = (
            "Get-CimInstance Win32_Process "
            "| Where-Object { "
            "($_.Name -like 'python*.exe' -or $_.Name -eq 'py.exe') "
            f"-and $_.CommandLine -like '*{escaped}*' "
            "-and $_.CommandLine -notlike '*stop_*' "
            "} | ForEach-Object { $_.ProcessId }"
        )
        pids: list[int] = []
        for line in _run_powershell(script).splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return pids
    else:
        pids = []
        for proc_dir in Path("/proc").glob("[0-9]*"):
            try:
                cmdline_path = proc_dir / "cmdline"
                if not cmdline_path.is_file():
                    continue
                cmdline = cmdline_path.read_text(encoding="utf-8", errors="ignore")
                cmd_args = [arg for arg in cmdline.split("\x00") if arg]
                if not cmd_args:
                    continue
                full_cmd = " ".join(cmd_args)
                if marker in full_cmd and "stop_" not in full_cmd:
                    comm_path = proc_dir / "comm"
                    comm_name = ""
                    if comm_path.is_file():
                        comm_name = comm_path.read_text(encoding="utf-8", errors="ignore").strip()
                    
                    is_python = (
                        comm_name.startswith("python") or 
                        comm_name == "py" or 
                        "python" in cmd_args[0] or 
                        cmd_args[0] == "py"
                    )
                    if is_python:
                        pids.append(int(proc_dir.name))
            except (OSError, ValueError):
                continue
        return sorted(set(pids))


def get_parent_pid(pid: int) -> int | None:
    if sys.platform == "win32":
        script = (
            f'(Get-CimInstance Win32_Process -Filter "ProcessId = {pid}" '
            "| Select-Object -ExpandProperty ParentProcessId)"
        )
        value = _run_powershell(script).strip()
        if value.isdigit():
            return int(value)
        return None
    else:
        try:
            status_text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="ignore")
            for line in status_text.splitlines():
                if line.startswith("PPid:"):
                    return int(line.split()[1])
        except (OSError, IndexError, ValueError):
            pass
        return None


def get_process_name(pid: int) -> str:
    if sys.platform == "win32":
        script = (
            f'(Get-CimInstance Win32_Process -Filter "ProcessId = {pid}" '
            "| Select-Object -ExpandProperty Name)"
        )
        return _run_powershell(script).strip().lower()
    else:
        try:
            return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="ignore").strip().lower()
        except OSError:
            return ""


def find_launcher_cmd_pids(start_bat_marker: str, *, exclude_pids: set[int]) -> list[int]:
    """Find orphaned start-.bat CMD windows, excluding the caller's shell."""
    if sys.platform == "win32":
        escaped = start_bat_marker.replace("'", "''")
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name = 'cmd.exe'\" "
            f"| Where-Object {{ $_.CommandLine -like '*{escaped}*' }} "
            "| Select-Object ProcessId, CommandLine "
            "| ConvertTo-Json -Compress"
        )
        raw = _run_powershell(script).strip()
        if not raw:
            return []

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []

        payloads = payload if isinstance(payload, list) else [payload]
        pids: list[int] = []
        for row in payloads:
            pid = int(row.get("ProcessId", 0))
            if pid <= 0 or pid in exclude_pids:
                continue
            pids.append(pid)
        return pids
    else:
        return []



def _exclude_pids() -> set[int]:
    return {os.getpid(), os.getppid()}


def _collect_targets(
    *,
    runner_marker: str,
    start_bat_marker: str,
    exclude: set[int],
    close_launcher_windows: bool,
) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []

    for pid in find_pids_by_commandline(runner_marker):
        if pid in exclude:
            continue
        targets.append((pid, "python"))

        if not close_launcher_windows:
            continue

        parent_pid = get_parent_pid(pid)
        if parent_pid and parent_pid not in exclude and get_process_name(parent_pid) == "cmd.exe":
            targets.append((parent_pid, "launcher"))

    if close_launcher_windows:
        for pid in find_launcher_cmd_pids(start_bat_marker, exclude_pids=exclude):
            targets.append((pid, "launcher"))

    return targets


def _remaining_pids(
    *,
    runner_marker: str,
    start_bat_marker: str,
    exclude: set[int],
    close_launcher_windows: bool,
) -> list[tuple[int, str]]:
    remaining: list[tuple[int, str]] = []
    for pid in find_pids_by_commandline(runner_marker):
        if pid not in exclude:
            remaining.append((pid, "python"))
    if close_launcher_windows:
        for pid in find_launcher_cmd_pids(start_bat_marker, exclude_pids=exclude):
            remaining.append((pid, "launcher"))
    return remaining


def _kill_targets(targets: list[tuple[int, str]], *, exclude: set[int], bot_name: str) -> int:
    killed = 0
    seen: set[int] = set()
    for pid, kind in targets:
        if pid in seen or pid in exclude:
            continue
        seen.add(pid)
        if kill_pid(pid):
            label = "launcher window" if kind == "launcher" else "process"
            print(f"Stopped {bot_name} {label} PID {pid}")
            killed += 1
        else:
            label = "launcher window" if kind == "launcher" else "process"
            print(f"WARNING: taskkill failed for {bot_name} {label} PID {pid}")
    return killed


def stop_bot_instance(
    *,
    runner_marker: str,
    start_bat_marker: str,
    lock_path: Path,
    bot_name: str,
    close_launcher_windows: bool = True,
    max_retry_seconds: float | None = None,
    retry_interval: float | None = None,
) -> int:
    """Stop bot process(es), optionally close launcher CMD, remove lock.

    Retries for up to ``max_retry_seconds`` when targets remain alive.
    Returns 0 on success, 1 if processes/windows still running after retries.
    """
    if max_retry_seconds is None:
        max_retry_seconds = (
            SILENT_RETRY_SECONDS if not close_launcher_windows else DEFAULT_RETRY_SECONDS
        )
    if retry_interval is None:
        retry_interval = (
            SILENT_RETRY_INTERVAL if not close_launcher_windows else DEFAULT_RETRY_INTERVAL
        )

    deadline = time.monotonic() + max_retry_seconds
    attempt = 0
    total_killed = 0
    had_targets = False
    pid_lock = lock_path.with_suffix(".pidlock")

    def _remove_lock_files() -> None:
        from core.instance_lock import remove_lock_files

        if remove_lock_files(lock_path):
            print(f"Removed {lock_path.name}")

    while True:
        attempt += 1
        exclude = _exclude_pids()
        remaining = _remaining_pids(
            runner_marker=runner_marker,
            start_bat_marker=start_bat_marker,
            exclude=exclude,
            close_launcher_windows=close_launcher_windows,
        )

        if not remaining:
            _remove_lock_files()
            if total_killed == 0 and not had_targets:
                print(f"No running {bot_name} instance found.")
            elif total_killed > 0:
                print(f"Stopped {total_killed} {bot_name} target(s).")
            else:
                print(f"{bot_name} stop verified — no processes remain.")
            print(
                f"VERIFY: {bot_name} STOPPED — no {runner_marker} processes. "
                f"Run: {'.venv/bin/python' if sys.platform != 'win32' else '.venv\\\\Scripts\\\\python.exe'} scripts/bot_status.py all"
            )
            return 0

        had_targets = True
        if attempt == 1:
            print(f"Stopping {bot_name}…")
        else:
            print(f"Retry {attempt - 1}: {bot_name} still running, retrying…")

        targets = _collect_targets(
            runner_marker=runner_marker,
            start_bat_marker=start_bat_marker,
            exclude=exclude,
            close_launcher_windows=close_launcher_windows,
        )
        total_killed += _kill_targets(targets, exclude=exclude, bot_name=bot_name)

        time.sleep(0.4)
        exclude = _exclude_pids()
        still = _remaining_pids(
            runner_marker=runner_marker,
            start_bat_marker=start_bat_marker,
            exclude=exclude,
            close_launcher_windows=close_launcher_windows,
        )
        if not still:
            _remove_lock_files()
            print(f"Stopped {total_killed} {bot_name} target(s).")
            print(
                f"VERIFY: {bot_name} STOPPED — no {runner_marker} processes. "
                f"Run: {'.venv/bin/python' if sys.platform != 'win32' else '.venv\\\\Scripts\\\\python.exe'} scripts/bot_status.py all"
            )
            return 0

        if time.monotonic() >= deadline:
            print()
            print(f"ERROR: Could not fully stop {bot_name} after {attempt} attempt(s).")
            for pid, kind in still:
                label = "launcher window" if kind == "launcher" else "process"
                print(f"  Still running: {label} PID {pid}")
            print()
            print("Close the start window manually or run this stop script again.")
            return 1

        wait = min(retry_interval, max(0.0, deadline - time.monotonic()))
        if wait > 0:
            time.sleep(wait)
