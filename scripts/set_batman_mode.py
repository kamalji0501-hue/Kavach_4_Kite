#!/usr/bin/env python3
"""Set config/batman_mode.json — called from Mode/*.bat."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Set Batman mode (dev | uat | prod)")
    parser.add_argument("mode", choices=["dev", "uat", "prod"])
    args = parser.parse_args()

    from core.batman_mode import get_mode, prod_hostname_guard, set_mode

    path = set_mode(args.mode, ROOT)
    print(f"Batman mode set to: {args.mode.upper()}")
    print(f"  config file : {path}")
    print(f"  data folder : {ROOT / 'data' / args.mode}")
    print(f"  log folder  : {ROOT / f'logs_{args.mode}'}")

    warn = prod_hostname_guard(ROOT)
    if warn:
        print(f"\n  WARNING: {warn}")

    if args.mode == "uat":
        shot_dir = ROOT / "uat" / "deployed_positions"
        print(f"\n  UAT screenshot folder:")
        print(f"    {shot_dir}")
        print("  Paste your Sensibull screenshot there (any filename .png/.jpg).")
        print("  Then run: Mode\\Prepare-UAT.bat")

    print(f"\n  Active mode now: {get_mode(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
