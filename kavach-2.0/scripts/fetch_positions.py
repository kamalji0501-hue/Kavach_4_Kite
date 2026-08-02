#!/usr/bin/env python3
"""Fetch live Dhan positions (Gate 3 smoke — read-only, no secrets printed)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from dotenv import dotenv_values

    from core.broker import BatmanBroker
    from core.positions import filter_nifty_positions, format_position_summary
    from core.token_store import TokenStore

    env = dotenv_values(ROOT / "config" / ".env")
    client_code = (env.get("DHAN_CLIENT_CODE") or "").strip()
    store = TokenStore(path=ROOT / "data" / "access_token.json")
    token, saved_at = store.load()

    print("=== Dhan positions fetch (KAVACH Gate 3) ===\n")
    print(f"  client_code : {client_code or '(missing)'}")
    print(f"  dhan_jwt    : {'present' if token else 'missing'}")
    print(f"  saved_at    : {saved_at}")
    print(f"  age_hours   : {store.token_age_hours()}")
    print(f"  expired     : {store.is_expired()}\n")

    if not client_code or not token:
        print("BLOCKED: Send a fresh Dhan JWT to DRISHTI first.")
        return 1

    try:
        broker = BatmanBroker.connect_with_token(client_code, token)
        df = broker.get_positions()
        raw_count = 0 if df is None else len(df)
        open_count = 0
        if df is not None and hasattr(df, "empty") and not df.empty and "netQty" in df.columns:
            open_count = int((df["netQty"].fillna(0).astype(int) != 0).sum())

        nifty = filter_nifty_positions(df)
        print(f"  raw rows    : {raw_count}")
        print(f"  open rows   : {open_count}")
        print(f"  NIFTY opts  : {len(nifty)}\n")
        print(format_position_summary(nifty).replace("₹", "Rs "))
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
