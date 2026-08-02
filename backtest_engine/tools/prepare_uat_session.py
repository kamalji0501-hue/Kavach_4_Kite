#!/usr/bin/env python3
"""
Prepare UAT session from uat/deployed_positions/ screenshot.

1. Finds newest image (any filename).
2. Requires or creates positions.json (Sensibull legs).
3. Runs validate_fixture when JWT + positions.json exist.

Paste screenshot only — run this bat after Set-UAT.bat.
If positions.json is missing but an image exists, writes a stub only when
--from-image is implemented; otherwise prints clear next step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from core.batman_mode import get_mode, set_mode, uat_screenshot_dir
    from core.uat_positions import find_screenshot_images, positions_json_path

    parser = argparse.ArgumentParser(description="Prepare UAT from screenshot folder")
    parser.add_argument("--force-mode-uat", action="store_true", help="Set mode to uat if not already")
    args = parser.parse_args()

    if args.force_mode_uat and get_mode(ROOT) != "uat":
        set_mode("uat", ROOT)

    mode = get_mode(ROOT)
    if mode != "uat":
        print(f"BLOCKED: batman mode is {mode!r}. Run Mode\\Set-UAT.bat first.")
        return 1

    shot_dir = uat_screenshot_dir(ROOT)
    shot_dir.mkdir(parents=True, exist_ok=True)
    images = find_screenshot_images(shot_dir)
    pos_path = positions_json_path(ROOT)

    print("=== UAT prepare ===\n")
    print(f"  mode           : {mode}")
    print(f"  screenshot dir : {shot_dir}\n")

    if images:
        print(f"  screenshot     : {images[0].name} ({len(images)} image(s) in folder)")
    else:
        print("  screenshot     : (none — OK if positions.json already exists)")

    if not pos_path.is_file():
        if not images:
            print("\nBLOCKED: No screenshot and no positions.json.")
            print("  Paste Sensibull PNG/JPG in deployed_positions, then ask Batman to parse it.")
            return 1
        print("\nBLOCKED: positions.json not found.")
        print("  Ask Batman (Cursor) to parse the UAT screenshot in uat/deployed_positions/")
        print(f"  Target file: {pos_path}")
        return 1

    with open(pos_path, encoding="utf-8") as fh:
        fixture = json.load(fh)
    print(f"  positions.json : OK ({len(fixture.get('legs', []))} legs)")

    print("\nRunning validate_fixture (JWT + Dhan symbols)...\n")
    import subprocess

    rc = subprocess.call(
        [sys.executable, str(ROOT / "backtest_engine" / "tools" / "validate_fixture.py"), "--fixture", str(pos_path)],
        cwd=str(ROOT),
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
