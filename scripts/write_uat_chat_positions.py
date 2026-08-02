#!/usr/bin/env python3
"""Write uat/deployed_positions/positions.json from agent-extracted Sensibull legs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.uat_chat_positions import UATChatPositionsError, build_fixture, write_positions_json


def _parse_expiry(s: str) -> str:
    from core.nifty_option_expiry import parse_expiry_label

    return parse_expiry_label(s.strip()).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Write UAT positions.json (cursor_chat source)")
    parser.add_argument("--expiry", required=True, help="ISO date or '09 Jun 2026'")
    parser.add_argument("--json", type=Path, help="Full fixture JSON file")
    parser.add_argument("--stdin", action="store_true", help="Read fixture JSON from stdin")
    parser.add_argument("--spot", type=float, default=0, help="NIFTY spot at capture (0=auto)")
    parser.add_argument("--image", default="cursor-chat", help="Source image label")
    args = parser.parse_args()

    if args.json:
        fixture = json.loads(args.json.read_text(encoding="utf-8"))
    elif args.stdin:
        fixture = json.load(sys.stdin)
    else:
        print("Provide --json or --stdin", file=sys.stderr)
        return 2

    if "expiry_date" not in fixture and args.expiry:
        fixture["expiry_date"] = _parse_expiry(args.expiry)
    if args.spot > 0:
        fixture["spot_at_capture"] = args.spot
    if args.image:
        fixture["source_image"] = args.image

    try:
        if "legs" in fixture and fixture.get("source") != "cursor_chat":
            fixture = build_fixture(
                expiry_date=fixture["expiry_date"],
                legs=fixture["legs"],
                spot_at_capture=fixture.get("spot_at_capture"),
                source_image=fixture.get("source_image", args.image),
            )
        else:
            fixture["source"] = "cursor_chat"
            from core.uat_chat_positions import validate_fixture

            validate_fixture(fixture)
        path = write_positions_json(fixture)
    except (UATChatPositionsError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
