#!/usr/bin/env python3
"""Post Phase-1-start verification: process status + credential smoke (no chat spam)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import get_venv_python

from core.bot_process_status import BotRunState, classify_bot, format_status_line
from core.startup_gates import nifty_cache_age_seconds, wait_drishti_ltp_ready


def run_verify(*, require_ltp: bool = False, ltp_timeout: float = 30.0) -> int:
    print("=== Phase 1 post-start verify ===")
    failures: list[str] = []

    for robot in ("drishti", "kavach2", "jagran"):
        status = classify_bot(robot, root=ROOT)
        print(format_status_line(status))
        if status.state is not BotRunState.RUNNING:
            failures.append(f"{robot.upper()} not RUNNING")

    if require_ltp:
        ok, detail = wait_drishti_ltp_ready(timeout_seconds=ltp_timeout, root=ROOT)
        print(f"DRISHTI LTP gate: {detail}")
        if not ok:
            failures.append(detail)
    else:
        age = nifty_cache_age_seconds(root=ROOT)
        if age is not None:
            print(f"NIFTY cache age: {age:.0f}s")


    py = get_venv_python(ROOT)
    rc = subprocess.run(
        [str(py), str(ROOT / "scripts" / "audit_bot_tokens.py")],
        cwd=ROOT,
        check=False,
    ).returncode
    if rc != 0:
        failures.append("audit_bot_tokens failed")

    warnings: list[str] = []
    from core.optional_bot_startup import optional_bot_enabled

    saransh_ok, saransh_reason = optional_bot_enabled("saransh", root=ROOT)
    if saransh_ok:
        saransh_status = classify_bot("saransh", root=ROOT)
        print(format_status_line(saransh_status))
        if saransh_status.state is not BotRunState.RUNNING:
            warnings.append("SARANSH eligible but not RUNNING (optional — core trio OK)")
    else:
        print(f"SARANSH: skipped ({saransh_reason})")
        warnings.append(f"SARANSH skipped: {saransh_reason}")

    if failures:
        print("\nVERIFY FAIL:")
        for line in failures:
            print(f"  - {line}")
        return 1

    if warnings:
        print("\nVERIFY PASS (with optional-bot notes):")
        for line in warnings:
            print(f"  - {line}")
    else:
        print("\nVERIFY PASS: all Phase 1 bots RUNNING")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Phase 1 bots after start-all.")
    parser.add_argument(
        "--require-ltp",
        action="store_true",
        help="Require fresh DRISHTI NIFTY cache (market hours)",
    )
    parser.add_argument("--ltp-timeout", type=float, default=30.0)
    args = parser.parse_args()
    return run_verify(require_ltp=args.require_ltp, ltp_timeout=args.ltp_timeout)


if __name__ == "__main__":
    raise SystemExit(main())
