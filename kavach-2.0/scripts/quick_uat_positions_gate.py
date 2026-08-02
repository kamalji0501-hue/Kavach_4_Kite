#!/usr/bin/env python3
"""
Fast UAT book update — NO bot restart.

Use when Phase 1 bots are already RUNNING and you only changed the Sensibull
screenshot book (cursor_chat positions.json). KAVACH reloads the fixture on
the next Register tap (refresh_fixture_positions) — no process restart needed.

Agent workflow after writing positions.json from screenshot:
  .venv\\Scripts\\python.exe scripts\\quick_uat_positions_gate.py

Full daily suite + restart: only after KAVACH code changes, dead bots, or
first session of the day when you want startup log proof.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.utils import get_venv_python


PYTHON = get_venv_python(ROOT)


def _run_validate_fixture(*, full: bool) -> int:
    from core.uat_positions import positions_json_path

    pos = positions_json_path(ROOT)
    # Also keep repo-relative path in sync for operator docs / tools that hardcode it
    legacy = ROOT / "uat" / "deployed_positions" / "positions.json"
    if pos.is_file() and pos.resolve() != legacy.resolve():
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(pos.read_bytes())
    cmd = [
        str(PYTHON),
        str(ROOT / "backtest_engine" / "tools" / "validate_fixture.py"),
        "--fixture",
        str(pos if pos.is_file() else legacy),
    ]
    if not full:
        cmd.append("--skip-chain")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return proc.returncode


def _bot_running(name: str) -> bool:
    from core.bot_process_status import BotRunState, classify_bot

    st = classify_bot(name)
    return st.state is BotRunState.RUNNING


def main() -> int:
    parser = argparse.ArgumentParser(description="Quick UAT positions gate (no bot restart)")
    parser.add_argument("--skip-validate", action="store_true", help="Skip validate_fixture entirely")
    parser.add_argument(
        "--full-validate",
        action="store_true",
        help="Full validate_fixture including slow option-chain cross-check",
    )
    parser.add_argument("--no-cleanup", action="store_true", help="Skip prepare_uat_register_fresh")
    args = parser.parse_args()
    t0 = time.perf_counter()

    from core.batman_mode import get_mode, workspace_root
    from core.uat_chat_positions import load_positions_json, validate_fixture
    from core.uat_positions import positions_json_path

    root = workspace_root()
    mode = get_mode(root)
    if mode != "uat":
        print(f"BLOCKED: mode={mode!r} — run Mode\\Set-UAT.bat")
        return 1

    pos_path = positions_json_path(root)
    if not pos_path.is_file():
        print(f"BLOCKED: missing {pos_path}")
        return 1

    data = load_positions_json(root)
    if not data:
        print(f"BLOCKED: invalid JSON at {pos_path}")
        return 1
    try:
        validate_fixture(data)
    except Exception as exc:
        print(f"BLOCKED: positions.json invalid — {exc}")
        return 1

    print("=== Quick UAT positions gate (no restart) ===\n")
    print(f"  file   : {pos_path}")
    print(f"  source : {data.get('source')}")
    print(f"  expiry : {data.get('expiry_date')} ({data.get('expiry_label')})")
    print(f"  legs   : {len(data.get('legs') or [])}")
    for leg in data.get("legs") or []:
        print(
            f"    {leg.get('role_hint')}: {leg.get('side')} {leg.get('strike')} "
            f"{leg.get('type')} x{leg.get('lots')} @ {leg.get('avg_price')}"
        )
    print()

    if not args.skip_validate:
        label = "validate_fixture (JWT + Dhan symbols)" + (
            "" if args.full_validate else ", skip chain"
        )
        print(f"Running {label}...")
        if _run_validate_fixture(full=args.full_validate) != 0:
            print("\nFAIL: validate_fixture")
            return 1
        print()

    # Phase 1 uses KAVACH 2.0 (legacy kavach is retired).
    core = ("drishti", "kavach2", "jagran")
    running = {n: _bot_running(n) for n in core}
    stopped = [n for n, ok in running.items() if not ok]
    for n, ok in running.items():
        label = "KAVACH 2.0" if n == "kavach2" else n.upper()
        print(f"  {label}: {'RUNNING' if ok else 'STOPPED'}")
    if stopped:
        print(f"\nWARN: {', '.join(stopped)} not running — start via Execution/Start Bots/")
        print("      (Quick gate does not restart bots; Register needs KAVACH 2.0 up.)")
    print()

    if not args.no_cleanup:
        from core.state import StateManager
        from core.batman_mode import state_path
        from core.uat_register_cleanup import prepare_uat_register_fresh

        state = StateManager(path=state_path(root))
        summary = prepare_uat_register_fresh(root, state=state, broker=None)
        print("Cleanup (disk only — KAVACH 2.0 picks up on Register):")
        print(json.dumps({k: v for k, v in summary.items() if k != "deploy_dir"}, indent=2))
        print()

    elapsed = time.perf_counter() - t0
    print(f"OK: quick gate passed in {elapsed:.1f}s — bots need NOT restart for a new book.")
    print(">>> Tap Register in KAVACH 2.0 Telegram.")
    print("    Expect log: UAT register: using cursor_chat positions.json (skip OCR)")
    return 0 if not stopped else 2


if __name__ == "__main__":
    raise SystemExit(main())
