#!/usr/bin/env python3
"""Smoke-test Telegram bot credentials from the desktop/runtime secrets folder.

Reads ``<secrets_root>/telegram/bots.env`` (consolidated) and verifies each
configured bot can be loaded by code and accepted by Telegram ``getMe``.

Usage (from code tree)::

    .venv/bin/python scripts/smoke_telegram_bots.py
    .venv/bin/python scripts/smoke_telegram_bots.py --bots drishti,kavach,jagran,saransh
    .venv/bin/python scripts/smoke_telegram_bots.py --load-only   # no network getMe

Exit codes: 0 = all present bots passed; 1 = one or more failed; 2 = no credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bat_telegram.loader import load_bot_config, reload_all  # noqa: E402
from core.batman_mode import ensure_runtime_layout, secrets_root  # noqa: E402
from core.telegram_credentials import (  # noqa: E402
    get_bot_credentials,
    is_placeholder,
    list_bots_with_credentials,
    secrets_telegram_bots_env_path,
)

DEFAULT_BOTS = ["drishti", "kavach", "jagran", "saransh"]


def _get_me(token: str, timeout: float = 15.0) -> tuple[bool, str]:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        return False, f"HTTP {exc.code}: {body}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if not payload.get("ok"):
        return False, f"getMe not ok: {payload}"
    result = payload.get("result") or {}
    uname = result.get("username") or "?"
    bid = result.get("id") or "?"
    return True, f"@{uname} id={bid}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test Telegram bot credentials")
    ap.add_argument(
        "--bots",
        default=",".join(DEFAULT_BOTS),
        help="Comma-separated bot names (default: phase-1 four)",
    )
    ap.add_argument(
        "--all-known",
        action="store_true",
        help="Include every bot that has a token in desktop credentials",
    )
    ap.add_argument(
        "--load-only",
        action="store_true",
        help="Only verify code can read tokens (skip Telegram getMe)",
    )
    args = ap.parse_args()

    ensure_runtime_layout(ROOT)
    cons = secrets_telegram_bots_env_path(ROOT)
    print(f"secrets_root = {secrets_root(ROOT)}")
    print(f"bots.env     = {cons}  exists={cons.is_file()}")

    names = [b.strip().lower() for b in args.bots.split(",") if b.strip()]
    if args.all_known:
        from bat_telegram.loader import bot_names

        names = bot_names()

    inventory = list_bots_with_credentials(names, ROOT)
    present = [r for r in inventory if r["has_token"] == "yes"]
    if not present:
        print("FAIL: no bot tokens found on desktop credentials")
        for r in inventory:
            print(f"  - {r['bot']}: token={r['has_token']} chat={r['has_chat_id']} src={r['source']}")
        return 2

    print("\nInventory (no secrets printed):")
    for r in inventory:
        print(
            f"  {r['bot']:10} token={r['has_token']:3} chat={r['has_chat_id']:3}  source={r['source']}"
        )

    reload_all()
    passed = 0
    failed = 0
    skipped = 0
    print("\nSmoke results:")
    for r in inventory:
        name = r["bot"]
        if r["has_token"] != "yes":
            print(f"  SKIP  {name:10} — no token on this machine")
            skipped += 1
            continue
        try:
            cfg = load_bot_config(name, reload_token=True)
            if is_placeholder(cfg.bot_token):
                raise KeyError("placeholder token")
            load_ok = True
            load_msg = f"loaded chat_set={bool(cfg.chat_id and not is_placeholder(cfg.chat_id))}"
        except Exception as exc:  # noqa: BLE001
            load_ok = False
            load_msg = f"{type(exc).__name__}: {exc}"

        if not load_ok:
            print(f"  FAIL  {name:10} read: {load_msg}")
            failed += 1
            continue

        if args.load_only:
            print(f"  PASS  {name:10} {load_msg}")
            passed += 1
            continue

        tok, _, _ = get_bot_credentials(name, ROOT)
        ok, detail = _get_me(tok)
        if ok:
            print(f"  PASS  {name:10} {load_msg} | getMe {detail}")
            passed += 1
        else:
            print(f"  FAIL  {name:10} read OK but getMe failed: {detail}")
            failed += 1

    print(f"\nSummary: passed={passed} failed={failed} skipped={skipped}")
    if failed:
        return 1
    if passed == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
