#!/usr/bin/env python3
"""Off-hours reliability suite: pytest + incident verify + lifecycle cycles (no live NIFTY)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.utils import get_venv_python
PY = get_venv_python(ROOT)


def _run(cmd: list[str], *, label: str) -> int:
    print(f"\n=== {label} ===")
    proc = subprocess.run(cmd, cwd=str(ROOT), check=False)
    print(f"{label}: exit {proc.returncode}")
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run off-hours reliability validation suite.")
    parser.add_argument("--cycles", type=int, default=5, help="Lifecycle cycles (use 15 on market day)")
    parser.add_argument("--wait-seconds", type=float, default=120.0)
    parser.add_argument("--skip-lifecycle", action="store_true")
    args = parser.parse_args()

    failures = 0

    failures += _run(
        [str(PY), "-m", "pytest", "tests/test_reliability_fault_injection.py", "tests/test_telegram_runtime.py", "-q", "--tb=short"],
        label="Fault injection + Telegram runtime pytest",
    )

    failures += _run(
        [str(PY), "scripts/stabilization_verify.py"],
        label="Stabilization verify (3 cycles, off-hours cache aware)",
    )

    failures += _run(
        [str(PY), "scripts/verify_incident_fixes.py"],
        label="Incident fix verification",
    )

    if not args.skip_lifecycle:
        failures += _run(
            [
                str(PY),
                "scripts/run_phase1_reliability_loop.py",
                "--cycles",
                str(max(1, args.cycles)),
                "--wait-seconds",
                str(max(60.0, args.wait_seconds)),
            ],
            label=f"Lifecycle harness ({args.cycles} cycles)",
        )

    failures += _run(
        [str(PY), "scripts/generate_reliability_engineering_report.py"],
        label="Generate engineering report",
    )

    print("\n=== Off-hours suite summary ===")
    if failures:
        print(f"FAILED steps: {failures}")
        return 1
    print("ALL OFF-HOURS STEPS PASSED")
    print("Live NIFTY validation: see docs/RELIABILITY_MARKET_HOURS_DEFERRED.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
