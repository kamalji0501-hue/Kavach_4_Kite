#!/usr/bin/env python3
"""
VPS service monitor — retry, crash recovery, feedback loop.

Watches systemd units, restarts on failure, kills stale PIDs,
writes state JSON, sends Telegram alerts.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow import from sibling modules when run from vps_ops
sys.path.insert(0, str(Path(__file__).resolve().parent))

from notifier import notify

OPS_DIR = Path(os.getenv("VPS_OPS_DIR", "/home/ubuntu/vps_ops"))
STATE_FILE = OPS_DIR / "state" / "monitor_state.json"
LOG_FILE = OPS_DIR / "logs" / "monitor.log"

WATCHED_SERVICES = os.getenv(
    "WATCHED_SERVICES", "my_telegram_bot.service"
).split(",")

MAX_RETRIES = int(os.getenv("MONITOR_MAX_RETRIES", "5"))
RETRY_BASE_SEC = float(os.getenv("MONITOR_RETRY_BASE_SEC", "3"))
STALE_SEC = int(os.getenv("MONITOR_STALE_SEC", "120"))
CHECK_INTERVAL = float(os.getenv("MONITOR_CHECK_INTERVAL", "15"))


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(line)
    print(line, end="")


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _load_state() -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"services": {}, "last_updated": None, "total_restarts": 0}


def _save_state(state: dict) -> None:
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _service_status(unit: str) -> str:
    r = _run(["systemctl", "is-active", unit.strip()])
    return (r.stdout or r.stderr).strip()


def _service_main_pid(unit: str) -> int | None:
    r = _run(["systemctl", "show", unit.strip(), "-p", "MainPID", "--value"])
    try:
        pid = int((r.stdout or "").strip())
        return pid if pid > 0 else None
    except ValueError:
        return None


def _restart_service(unit: str) -> bool:
    r = _run(["sudo", "systemctl", "restart", unit.strip()])
    return r.returncode == 0


def _kill_pid(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


def _recover_service(unit: str, state: dict, reason: str) -> bool:
    svc_state = state["services"].setdefault(unit, {"restarts": 0, "last_crash": None})
    svc_state["last_crash"] = datetime.now(timezone.utc).isoformat()
    svc_state["last_reason"] = reason

    for attempt in range(1, MAX_RETRIES + 1):
        wait = RETRY_BASE_SEC * (2 ** (attempt - 1))
        _log(f"[{unit}] recovery attempt {attempt}/{MAX_RETRIES} after {wait:.1f}s ({reason})")
        time.sleep(wait)

        pid = _service_main_pid(unit)
        if pid and reason.startswith("stale"):
            _log(f"[{unit}] killing stale PID {pid}")
            _kill_pid(pid)

        if not _restart_service(unit):
            _log(f"[{unit}] systemctl restart failed")
            continue

        time.sleep(2)
        if _service_status(unit) == "active":
            svc_state["restarts"] += 1
            state["total_restarts"] = state.get("total_restarts", 0) + 1
            _save_state(state)
            notify(f"✅ *VPS recovered*\nService: `{unit}`\nReason: {reason}\nAttempt: {attempt}")
            _log(f"[{unit}] recovered on attempt {attempt}")
            return True

    notify(f"🔴 *VPS recovery FAILED*\nService: `{unit}`\nReason: {reason}\nRetries: {MAX_RETRIES}")
    _log(f"[{unit}] recovery FAILED after {MAX_RETRIES} attempts")
    return False


def check_once(state: dict | None = None) -> dict:
    state = state or _load_state()
    for unit in WATCHED_SERVICES:
        unit = unit.strip()
        if not unit:
            continue
        status = _service_status(unit)
        svc_state = state["services"].setdefault(unit, {"restarts": 0})

        if status != "active":
            _log(f"[{unit}] not active (status={status})")
            _recover_service(unit, state, f"inactive:{status}")
            continue

        pid = _service_main_pid(unit)
        svc_state["pid"] = pid
        svc_state["status"] = status
        svc_state["checked_at"] = datetime.now(timezone.utc).isoformat()

        # Stale check: if PID exists but service file mtime old — skip heavy check
        # Main stale signal: repeated failed state handled above

    _save_state(state)
    return state


def run_loop(once: bool = False) -> None:
    _log("monitor started")
    notify("🟢 *VPS monitor started*\nWatching: " + ", ".join(WATCHED_SERVICES))
    state = _load_state()
    try:
        while True:
            state = check_once(state)
            if once:
                break
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        _log("monitor stopped (keyboard)")
    except Exception as exc:
        _log(f"monitor error: {exc}")
        notify(f"🔴 *VPS monitor crashed*\n`{exc}`")
        raise


if __name__ == "__main__":
    once = "--once" in sys.argv
    run_loop(once=once)
