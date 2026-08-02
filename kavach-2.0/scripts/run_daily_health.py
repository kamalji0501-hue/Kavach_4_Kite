#!/usr/bin/env python3
"""Daily Batman health loop — audit, bot status, optional start-all verify."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils import get_venv_python

_IST = ZoneInfo("Asia/Kolkata")
_PY = get_venv_python(ROOT)


def _run(script: str, *args: str) -> int:
    cmd = [str(_PY), str(ROOT / "scripts" / script), *args]
    print(f"\n>> {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily Batman health check.")
    parser.add_argument(
        "--start-all",
        action="store_true",
        help="Run phase1_start_all then post-start verify",
    )
    parser.add_argument(
        "--require-ltp",
        action="store_true",
        help="Pass --require-ltp to post-start verify",
    )
    args = parser.parse_args()

    now = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"=== Daily health — {now} ===")

    rc = 0
    for step, script, extra in (
        ("audit", "audit_bot_tokens.py", ()),
        ("status", "bot_status.py", ("all",)),
        ("diagnose", "diagnose_robot.py", ("drishti",)),
        ("diagnose", "diagnose_robot.py", ("kavach",)),
        ("diagnose", "diagnose_robot.py", ("jagran",)),
    ):
        if _run(script, *extra) != 0:
            rc = 1
            print(f"FAIL at {step}")

    if args.start_all:
        if _run("phase1_start_all.py", "--force") != 0:
            rc = 1
        verify_args = ["--require-ltp"] if args.require_ltp else []
        if _run("phase1_post_start_verify.py", *verify_args) != 0:
            rc = 1

    out = ROOT / "data" / "analytics" / "daily_health"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(_IST).strftime("%Y-%m-%d")
    latest = out / "LATEST_RUN.md"
    status = "PASS" if rc == 0 else "FAIL"
    latest.write_text(
        f"# Daily health {stamp}\n\nStatus: **{status}**\nTime: {now}\n",
        encoding="utf-8",
    )
    print(f"\n=== Daily health {status} — see {latest} ===")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
