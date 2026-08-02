#!/usr/bin/env python3
"""
Daily UAT test suite — runs all catalog cases, updates Excel matrix, writes LATEST_RUN.md.

Agent runs this after code changes (market hours: live LTP + bot checks).

Usage:
  .venv\\Scripts\\python.exe scripts\\run_uat_daily_test_suite.py
  .venv\\Scripts\\python.exe scripts\\run_uat_daily_test_suite.py --skip-bots
  .venv\\Scripts\\python.exe scripts\\run_uat_daily_test_suite.py --with-start

Prerequisites:
  Mode\\Set-UAT.bat
  uat\\deployed_positions\\ screenshot + positions.json
  data\\access_token.json (JWT via DRISHTI)
  For UAT-D08..D10: Phase 1 bots started via Execution\\Start Bots\\
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")

sys.path.insert(0, str(ROOT))

from core.utils import get_venv_python
PYTHON = get_venv_python(ROOT)


def _maybe_start_bots() -> None:
    script = ROOT / "scripts" / "phase1_start_all.py"
    if not script.is_file():
        return
    print("Starting Phase 1 bots (stop-first, up to 120s)...", flush=True)
    subprocess.run(
        [str(PYTHON), str(script), "--force"],
        cwd=str(ROOT),
        timeout=150,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily UAT test suite + Excel matrix")
    parser.add_argument("--skip-bots", action="store_true", help="Skip DRISHTI/KAVACH/JAGRAN process checks")
    parser.add_argument("--skip-slow", action="store_true", help="Skip validate_fixture, phase1_check, OCR, pytest")
    parser.add_argument(
        "--with-start",
        action="store_true",
        help="Run phase1_start_all before tests (operator bat preferred)",
    )
    args = parser.parse_args()

    if not PYTHON.is_file():
        print(f"Missing venv: {PYTHON}", file=sys.stderr)
        return 1

    from core.batman_mode import get_mode

    if get_mode(ROOT) != "uat":
        print("BLOCKED: run Mode\\Set-UAT.bat first.", file=sys.stderr)
        return 1

    if args.with_start:
        _maybe_start_bots()

    from core.daily_test_matrix import MATRIX_FILE, append_results, write_latest_summary
    from core.uat_daily_test_log import DailyTestLogger
    from core.uat_daily_tests import run_all_cases

    run_id = datetime.now(tz=IST).strftime("%Y%m%d_%H%M%S")
    suite_log = DailyTestLogger(run_id)
    print(f"\n=== UAT daily test suite run_id={run_id} ===\n", flush=True)
    print(f"Suite log: {suite_log.run_log_path.resolve()}", flush=True)
    t0 = time.perf_counter()
    results = run_all_cases(
        skip_bots=args.skip_bots,
        skip_slow=args.skip_slow,
        run_logger=suite_log,
    )
    elapsed = time.perf_counter() - t0

    matrix_path = append_results(results, run_id=run_id)
    passed = sum(1 for r in results if r.ok and not r.skipped)
    failed = sum(1 for r in results if not r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    suite_log.log_summary(
        passed=passed,
        failed=failed,
        skipped=skipped,
        elapsed_s=elapsed,
        matrix_path=matrix_path,
    )
    latest = write_latest_summary(
        results,
        matrix_path=matrix_path,
        run_id=run_id,
        elapsed_s=elapsed,
        log_path=suite_log.run_log_path,
    )

    def _safe(s: str) -> str:
        return s.encode("ascii", errors="replace").decode("ascii")

    for r in results:
        mark = "SKIP" if r.skipped else ("PASS" if r.ok else "FAIL")
        print(f"  [{mark}] {r.case_id}  {_safe(r.detail[:100])}", flush=True)

    print(
        f"\nSummary: PASS={passed} FAIL={failed} SKIP={skipped} ({elapsed:.1f}s)",
        flush=True,
    )
    print(f"Excel matrix: {matrix_path.resolve()}", flush=True)
    print(f"Latest report: {latest.resolve()}", flush=True)
    print(f"Suite log: {suite_log.run_log_path.resolve()}", flush=True)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
