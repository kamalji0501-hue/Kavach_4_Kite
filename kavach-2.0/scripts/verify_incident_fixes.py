#!/usr/bin/env python3
"""Verify all incident registry fixes are present in code + pytest."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.incident_fix_verification import run_full_verification  # noqa: E402


def main() -> int:
    ok, report_path = run_full_verification(run_pytest=True)
    print(f"Fix verification: {'PASS' if ok else 'FAIL'}")
    print(f"Report: {report_path.resolve()}")
    if not ok:
        text = report_path.read_text(encoding="utf-8")
        if "## Failed checks" in text:
            start = text.index("## Failed checks")
            end = text.index("## All checks") if "## All checks" in text else len(text)
            print(text[start:end])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
