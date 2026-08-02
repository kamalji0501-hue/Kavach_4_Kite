#!/usr/bin/env python3
"""
Write uat/deployed_positions/positions.json from the newest screenshot metadata.

Operator workflow: paste screenshot in folder, run via Cursor agent after
reading the image (this script is invoked by agent with --payload JSON).

Example:
  python backtest_engine/tools/write_uat_positions_from_image.py --payload-file payload.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-file", type=Path, required=True)
    args = parser.parse_args()

    from core.uat_positions import positions_json_path

    with open(args.payload_file, encoding="utf-8") as fh:
        data = json.load(fh)

    out = positions_json_path(ROOT)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")

    print(f"Wrote UAT positions: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
