#!/usr/bin/env python3
"""Ensure Kavach2 stays up (rahul_Changes / batman-kavach2.service)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("ensure_kavach2")

SERVICE = os.environ.get("BATMAN_KAVACH2_SERVICE", "batman-kavach2.service")
STATE_PATH = Path(
    os.environ.get(
        "KAVACH2_ENSURE_STATE",
        "/home/ubuntu/Trading_Runtime_Rahul/Data/data/shared/kavach2_ensure_state.json",
    )
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def service_active() -> bool:
    return _run(["systemctl", "is-active", SERVICE]).stdout.strip() == "active"


def ensure_service() -> str:
    if service_active():
        return "already_active"
    log.warning("%s inactive — starting", SERVICE)
    cp = _run(["sudo", "-n", "systemctl", "start", SERVICE])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "start failed")
    for _ in range(15):
        if service_active():
            return "started"
        time.sleep(1)
    raise RuntimeError(f"{SERVICE} still not active after start")


def main() -> int:
    status = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "service": SERVICE,
    }
    try:
        status["service_action"] = ensure_service()
        status["service_active"] = service_active()
        status["ok"] = bool(status["service_active"])
    except Exception as exc:
        status["ok"] = False
        status["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("ensure failed")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status))
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
