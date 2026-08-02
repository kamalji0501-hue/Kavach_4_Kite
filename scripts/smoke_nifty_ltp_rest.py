#!/usr/bin/env python3
"""Smoke: NIFTY LTP via REST marketfeed/ltp with existing JWT auth (diagnostic / fallback).

Optional tool — production primary LTP is WebSocket when configured.
Writes into the same shared cache path DRISHTI / KAVACH already consume.

Usage (from workspace root)::

    .venv/bin/python scripts/smoke_nifty_ltp_rest.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    env_path = ROOT / "config" / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        os.environ.setdefault(key, val)


def main() -> int:
    _load_dotenv()

    from core.batman_mode import access_token_path, nifty_ltp_cache_path, workspace_root
    from core.nifty_ltp import fetch_nifty_ltp_rest_with_retry
    from core.nifty_ltp_feed import read_nifty_ltp_cache, seed_nifty_ltp_cache
    from core.token_store import TokenStore

    root = workspace_root()
    token_path = access_token_path(root)
    cache_path = nifty_ltp_cache_path(root)

    # JWT / access-token — unchanged project auth (TokenStore / access_token.json).
    store = TokenStore(path=token_path)
    token, _saved_at = store.load()
    if not token:
        token = os.environ.get("DHAN_ACCESS_TOKEN") or ""
    client_id = (
        os.environ.get("DHAN_CLIENT_CODE")
        or os.environ.get("DHAN_CLIENT_ID")
        or ""
    )
    if not token or not client_id:
        print("RESULT: FAIL — JWT/access token or client_id missing")
        print(f"  token_path={token_path}")
        print(f"  token_present={bool(token)} client_id={client_id!r}")
        return 2

    print("auth method unchanged (JWT/access token)")
    print(f"  token_path={token_path}")
    print(f"  client_id={client_id}")

    try:
        ltp = fetch_nifty_ltp_rest_with_retry(client_id, token, max_attempts=3)
    except Exception as exc:
        from core.exceptions import BrokerAuthError

        print(f"nifty_ltp value= (fetch failed: {exc})")
        print(f"output file path (unchanged writer target)={cache_path}")
        print("websocket LTP opened=no (REST marketfeed/ltp only)")
        if isinstance(exc, BrokerAuthError):
            print("RESULT: BLOCKED — JWT/access token rejected by Dhan (auth path unchanged).")
            print("  Paste a fresh JWT via DRISHTI Update Token, then re-run this smoke.")
            return 4
        print(f"RESULT: FAIL — {type(exc).__name__}: {exc}")
        return 1

    print(f"nifty_ltp value={ltp}")

    seed_nifty_ltp_cache(ltp, source="dhan_rest", path=cache_path)
    snap = read_nifty_ltp_cache(cache_path)
    print(f"output file path updated={cache_path}")
    if snap:
        print(f"  cache_ltp={snap.ltp} source={snap.source}")
    else:
        print("RESULT: FAIL — cache readback empty")
        return 3

    # Confirm no WebSocket LTP connection was opened (this script never imports MarketFeed).
    print("websocket LTP opened=no (REST marketfeed/ltp only)")
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
