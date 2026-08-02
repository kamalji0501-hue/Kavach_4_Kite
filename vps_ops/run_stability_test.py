#!/usr/bin/env python3
"""
Stability test — kill watched service N times, verify auto-recovery.

Runs on VPS; reports timing and success rate.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from service_monitor import (
    CHECK_INTERVAL,
    MAX_RETRIES,
    RETRY_BASE_SEC,
    _load_state,
    _recover_service,
    _run,
    _service_main_pid,
    _service_status,
)

ITERATIONS = int(os.getenv("STABILITY_ITERATIONS", "10"))
SERVICE = os.getenv("STABILITY_SERVICE", "my_telegram_bot.service")
RESULTS_FILE = Path("/home/ubuntu/vps_ops/state/stability_results.json")


def _kill_main_pid(unit: str) -> bool:
    r = _run(["systemctl", "show", unit, "-p", "MainPID", "--value"])
    try:
        pid = int((r.stdout or "").strip())
    except ValueError:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


def run_test(iterations: int = ITERATIONS) -> dict:
    results = {
        "service": SERVICE,
        "iterations": iterations,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "runs": [],
        "success_count": 0,
        "fail_count": 0,
        "avg_recovery_sec": 0.0,
    }

    state = _load_state()

    for i in range(1, iterations + 1):
        print(f"\n=== Iteration {i}/{iterations} ===")
        t0 = time.perf_counter()

        killed = _kill_main_pid(SERVICE)
        time.sleep(1)
        status_after_kill = _service_status(SERVICE)
        print(f"  killed={killed} status_after_kill={status_after_kill}")

        # Wait for systemd auto-restart OR monitor recovery
        recovered = False
        deadline = time.perf_counter() + (MAX_RETRIES * RETRY_BASE_SEC * 8 + 30)
        while time.perf_counter() < deadline:
            if _service_status(SERVICE) == "active" and _service_main_pid(SERVICE):
                recovered = True
                break
            time.sleep(1)

        if not recovered:
            print("  systemd did not recover — invoking monitor recovery")
            recovered = _recover_service(SERVICE, state, "stability_test_kill")

        elapsed = time.perf_counter() - t0
        ok = recovered and _service_status(SERVICE) == "active"
        run = {
            "iteration": i,
            "killed": killed,
            "recovered": ok,
            "recovery_sec": round(elapsed, 2),
            "final_status": _service_status(SERVICE),
            "pid": _service_main_pid(SERVICE),
        }
        results["runs"].append(run)
        if ok:
            results["success_count"] += 1
        else:
            results["fail_count"] += 1
        print(f"  recovered={ok} time={elapsed:.2f}s pid={run['pid']}")

        time.sleep(2)

    times = [r["recovery_sec"] for r in results["runs"] if r["recovered"]]
    results["avg_recovery_sec"] = round(sum(times) / len(times), 2) if times else 0.0
    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    results["pass_rate"] = round(100 * results["success_count"] / iterations, 1)

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else ITERATIONS
    out = run_test(n)
    print("\n" + "=" * 50)
    print(f"PASS RATE: {out['pass_rate']}% ({out['success_count']}/{out['iterations']})")
    print(f"AVG RECOVERY: {out['avg_recovery_sec']}s")
    print(f"Results: {RESULTS_FILE}")
