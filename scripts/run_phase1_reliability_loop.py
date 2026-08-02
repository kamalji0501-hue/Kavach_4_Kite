#!/usr/bin/env python3
"""Phase 1 reliability loop: repeated start/verify/stop cycles with artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import get_venv_python

from core.bot_health import health_age_seconds, read_bot_health
from core.bot_process_status import BotRunState, classify_bot
from core.nifty_ltp_feed import read_nifty_ltp_cache
from core.startup_gates import ltp_gate_skip_reason
from scripts.phase1_post_start_verify import run_verify
from scripts.phase1_start_all import run_start_all
from scripts.phase1_stop_all import run_stop_all

PY = get_venv_python(ROOT)
ARTIFACT_DIR = ROOT / "data" / "analytics" / "reliability"


def _ts() -> str:
    return datetime.now().astimezone().isoformat()


def _run_subprocess(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _bot_snapshot() -> dict[str, object]:
    bots: dict[str, object] = {}
    for bot in ("drishti", "kavach", "jagran", "saransh"):
        status = classify_bot(bot, root=ROOT)
        health = read_bot_health(ROOT, bot)
        bots[bot] = {
            "state": status.state.value,
            "pids": list(status.pids),
            "instance_count": status.instance_count,
            "warnings": list(status.warnings),
            "health_age_seconds": health_age_seconds(health) if health else None,
            "health_status": health.get("status") if isinstance(health, dict) else None,
        }
    return bots


def _cache_snapshot() -> dict[str, object]:
    snap = read_nifty_ltp_cache()
    if snap is None:
        return {"present": False}
    return {
        "present": True,
        "ltp": snap.ltp,
        "source": snap.source,
        "feed_healthy": snap.feed_healthy,
        "age_seconds": round(snap.age_seconds(), 2),
        "collector": snap.collector,
        "collector_pid": snap.collector_pid,
    }


def _telegram_smoke() -> dict[str, object]:
    rc, out = _run_subprocess([str(PY), str(ROOT / "scripts" / "phase1_bot_check.py")])
    return {"rc": rc, "ok": rc == 0, "output": out[-4000:]}


def _unexpected_errors() -> dict[str, object]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    patterns = [
        "Traceback",
        "Unhandled exception",
        "Task exception was never retrieved",
        "RuntimeError",
        "JAGRAN publish failed",
        "polling exited",
    ]
    ist = ZoneInfo("Asia/Kolkata")
    today = datetime.now(ist)
    month_dir = today.strftime("%Y-%m")
    day_dir = today.strftime("%Y-%m-%d")
    log_roots = [ROOT / "logs_uat" / "runtime", ROOT / "logs" / "runtime"]
    hits: dict[str, int] = {}
    for pat in patterns:
        count = 0
        for log_root in log_roots:
            scan_dir = log_root / month_dir / day_dir
            if not scan_dir.is_dir():
                continue
            for log_file in scan_dir.rglob("all.log"):
                try:
                    text = log_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                count += sum(1 for line in text.splitlines() if pat in line)
        if count:
            hits[pat] = count
    return hits


def _price_flow_ok(cache: dict[str, object]) -> tuple[bool, str]:
    """Live feed required in session; off-hours only require last-known cache."""
    skip_reason = ltp_gate_skip_reason()
    if skip_reason is not None:
        if cache.get("present"):
            return True, f"off_hours_{skip_reason}_last_cache_ok"
        return True, f"off_hours_{skip_reason}_no_cache_expected"
    if bool(cache.get("present")) and bool(cache.get("feed_healthy")):
        return True, "live_session_feed_healthy"
    if cache.get("present"):
        return False, "live_session_cache_present_but_feed_unhealthy"
    return False, "live_session_cache_missing"


def _cycle_status_ok(snapshot: dict[str, object]) -> bool:
    bots = snapshot["bots"]
    assert isinstance(bots, dict)
    for bot in ("drishti", "kavach", "jagran"):
        info = bots[bot]
        assert isinstance(info, dict)
        if info["state"] != BotRunState.RUNNING.value:
            return False
        if int(info["instance_count"]) != 1:
            return False
    return True


def run_loop(*, cycles: int, wait_seconds: float, new_console: bool) -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    artifact_path = ARTIFACT_DIR / f"phase1_reliability_{run_id}.json"
    skip_reason = ltp_gate_skip_reason()
    report: dict[str, object] = {
        "run_id": run_id,
        "started_at": _ts(),
        "cycles_requested": cycles,
        "market_session": {
            "live_ltp_required": skip_reason is None,
            "ltp_gate_skip_reason": skip_reason,
        },
        "cycles": [],
    }
    overall_ok = True

    for cycle in range(1, cycles + 1):
        entry: dict[str, object] = {"cycle": cycle, "started_at": _ts()}
        print(f"\n=== Reliability cycle {cycle}/{cycles} ===")
        start_t = time.monotonic()
        start_rc = run_start_all(
            force=True,
            wait_seconds=wait_seconds,
            popup_on_failure=False,
            popup_on_success=False,
            use_supervisor=True,
        )
        entry["start_rc"] = start_rc
        entry["start_elapsed_seconds"] = round(time.monotonic() - start_t, 2)

        verify_rc = run_verify(require_ltp=False, ltp_timeout=30.0)
        entry["verify_rc"] = verify_rc
        entry["bots"] = _bot_snapshot()
        entry["cache"] = _cache_snapshot()
        entry["telegram"] = _telegram_smoke()
        entry["unexpected_errors"] = _unexpected_errors()
        entry["startup_success"] = start_rc == 0
        entry["robot_success"] = _cycle_status_ok(entry)
        cache = entry["cache"]
        assert isinstance(cache, dict)
        price_ok, price_mode = _price_flow_ok(cache)
        entry["price_flow_success"] = price_ok
        entry["price_flow_mode"] = price_mode
        entry["telegram_success"] = bool(entry["telegram"].get("ok"))
        entry["warnings"] = []
        if skip_reason is not None:
            entry["warnings"].append(f"live_nifty_validation_skipped:{skip_reason}")
        if entry["unexpected_errors"]:
            entry["warnings"].append("unexpected_log_patterns_detected")

        stop_t = time.monotonic()
        stop_rc = run_stop_all(silent=True, popup_on_failure=False)
        entry["stop_rc"] = stop_rc
        entry["stop_elapsed_seconds"] = round(time.monotonic() - stop_t, 2)
        entry["stopped_bots"] = _bot_snapshot()
        entry["shutdown_success"] = stop_rc == 0
        entry["final_status"] = (
            "PASS"
            if all(
                (
                    entry["startup_success"],
                    entry["robot_success"],
                    entry["price_flow_success"],
                    entry["telegram_success"],
                    entry["shutdown_success"],
                )
            )
            else "FAIL"
        )
        entry["ended_at"] = _ts()
        report["cycles"].append(entry)
        artifact_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if entry["final_status"] != "PASS":
            overall_ok = False
            print(f"Cycle {cycle}: FAIL")
            break
        print(f"Cycle {cycle}: PASS")
        if cycle < cycles:
            time.sleep(2.0)

    report["ended_at"] = _ts()
    report["overall_status"] = "PASS" if overall_ok and len(report["cycles"]) == cycles else "FAIL"
    artifact_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nArtifact: {artifact_path}")
    print(f"Overall: {report['overall_status']}")
    return 0 if report["overall_status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeated Phase 1 reliability cycles.")
    parser.add_argument("--cycles", type=int, default=15)
    parser.add_argument("--wait-seconds", type=float, default=180.0)
    parser.add_argument(
        "--new-console",
        action="store_true",
        help="Unused compatibility flag; supervisor console behavior is controlled elsewhere.",
    )
    args = parser.parse_args()
    return run_loop(cycles=max(1, args.cycles), wait_seconds=max(60.0, args.wait_seconds), new_console=args.new_console)


if __name__ == "__main__":
    raise SystemExit(main())
