#!/usr/bin/env python3
"""Phase 1 stabilization verification — multi-cycle runtime checks (agent-owned)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CYCLES = 3

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import get_venv_python
PY = get_venv_python(ROOT)


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _check_cache() -> tuple[bool, str]:
    from core.startup_gates import ltp_gate_skip_reason

    skip = ltp_gate_skip_reason()
    if skip is not None:
        return True, f"off_hours ({skip}) — live cache not required"

    cache = ROOT / "data" / "nifty_ltp_cache.json"
    if not cache.exists():
        return False, "missing nifty_ltp_cache.json"
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"cache JSON invalid: {exc}"
    ltp = payload.get("ltp")
    source = payload.get("source")
    if not ltp or float(ltp) <= 0:
        return False, "cache ltp missing or zero"
    return True, f"ltp={ltp} source={source}"


def _check_health_bots() -> tuple[bool, str]:
    from core.bot_health import health_age_seconds, read_bot_health

    details: list[str] = []
    ok_all = True
    for bot in ("drishti", "kavach", "jagran"):
        h = read_bot_health(ROOT, bot)
        if h is None:
            ok_all = False
            details.append(f"{bot}:no-health")
            continue
        age = health_age_seconds(h)
        if age is None or age > 120:
            ok_all = False
            details.append(f"{bot}:stale")
        else:
            details.append(f"{bot}:ok")
    return ok_all, " ".join(details)


def _safe_print(text: str) -> None:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def main() -> int:
    failures: list[str] = []
    print(f"=== Stabilization verify ({CYCLES} cycles) ===")

    for cycle in range(1, CYCLES + 1):
        print(f"\n--- Cycle {cycle}/{CYCLES} ---")
        rc, out = _run([str(PY), str(ROOT / "scripts" / "bot_status.py"), "all"])
        _safe_print(out[:800])
        if rc == 2:
            failures.append(f"cycle{cycle}: bot_status orphan/ghost (rc=2)")
        elif rc not in (0, 1):
            failures.append(f"cycle{cycle}: bot_status rc={rc}")

        rc, out = _run([str(PY), str(ROOT / "scripts" / "audit_bot_tokens.py")])
        if rc != 0:
            failures.append(f"cycle{cycle}: token audit failed")
        else:
            print("token audit: PASS")

        rc, out = _run([str(PY), str(ROOT / "scripts" / "phase1_bot_check.py")])
        if rc != 0:
            failures.append(f"cycle{cycle}: phase1_bot_check failed")
        else:
            print("phase1_bot_check: PASS")

        cache_ok, cache_detail = _check_cache()
        print(f"cache: {'PASS' if cache_ok else 'FAIL'} ({cache_detail})")
        if not cache_ok:
            failures.append(f"cycle{cycle}: cache {cache_detail}")

        health_ok, health_detail = _check_health_bots()
        print(f"health: {'PASS' if health_ok else 'WARN'} ({health_detail})")

        if cycle < CYCLES:
            time.sleep(2)

    rc, out = _run(
        [
            str(PY),
            "-m",
            "pytest",
            "tests/test_algo_control.py",
            "tests/test_nifty_ltp_failover.py",
            "tests/test_feed_recovery.py",
            "tests/test_nifty_ltp_feed.py",
            "tests/test_nifty_ltp.py",
            "tests/test_bot_process_status.py",
            "tests/test_bot_supervisor.py",
            "tests/test_token_watch.py",
            "tests/test_bot_health.py",
            "tests/test_telegram_runtime.py",
            "tests/test_reliability_fault_injection.py",
            "-q",
            "--tb=short",
        ]
    )
    print(f"\npytest stabilization suite: rc={rc}")
    if rc != 0:
        failures.append("pytest stabilization suite failed")
        print(out[-2000:])

    print("\n=== Summary ===")
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
