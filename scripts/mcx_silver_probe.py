#!/usr/bin/env python3
"""Read-only MCX SILVER futures LTP probe — same JWT as DRISHTI, not for NIFTY/ATO."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DHAN_LTP_URL = "https://api.dhan.co/v2/marketfeed/ltp"
_EXCHANGE_SEGMENT = "MCX_COMM"

# Resolved from Dhan compact security master (2026-06-25) — re-resolve if contract rolls.
SILVER_FUTURES = {
    "jul": {
        "label": "SILVER JUL FUT",
        "security_id": 464150,
        "trading_symbol": "SILVER-03Jul2026-FUT",
        "expiry": "2026-07-03",
    },
    "sep": {
        "label": "SILVER SEP FUT",
        "security_id": 471725,
        "trading_symbol": "SILVER-04Sep2026-FUT",
        "expiry": "2026-09-04",
    },
    "dec": {
        "label": "SILVER DEC FUT",
        "security_id": 495214,
        "trading_symbol": "SILVER-04Dec2026-FUT",
        "expiry": "2026-12-04",
    },
}


def _load_credentials() -> tuple[str, str]:
    load_dotenv(ROOT / "config" / ".env")
    client_code = os.environ.get("DHAN_CLIENT_CODE", "").strip()
    token_path = ROOT / "data" / "access_token.json"
    if not client_code or not token_path.is_file():
        raise SystemExit("Missing DHAN_CLIENT_CODE or data/access_token.json — start DRISHTI / paste JWT first.")
    payload = json.loads(token_path.read_text(encoding="utf-8"))
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise SystemExit("access_token.json has no token.")
    return client_code, token


def fetch_ltp(*, client_code: str, token: str, security_id: int) -> tuple[float | None, int, str]:
    headers = {
        "access-token": token,
        "client-id": client_code,
        "Content-Type": "application/json",
    }
    body = {_EXCHANGE_SEGMENT: [security_id]}
    response = httpx.post(_DHAN_LTP_URL, headers=headers, json=body, timeout=20.0)
    if response.status_code != 200:
        return None, response.status_code, response.text[:240]
    data = response.json().get("data") if response.content else {}
    block = data.get(_EXCHANGE_SEGMENT) if isinstance(data, dict) else {}
    quote = block.get(str(security_id)) if isinstance(block, dict) else None
    if not isinstance(quote, dict):
        return None, response.status_code, f"No quote in response: {response.text[:240]}"
    ltp = quote.get("last_price")
    return (float(ltp) if ltp is not None else None), response.status_code, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe MCX SILVER futures LTP via Dhan (connectivity only).")
    parser.add_argument(
        "--contract",
        choices=sorted(SILVER_FUTURES),
        default="jul",
        help="Which SILVER futures month (default: jul — matches Sensibull snapshot)",
    )
    parser.add_argument("--samples", type=int, default=3, help="Number of LTP samples (2s apart)")
    args = parser.parse_args()

    meta = SILVER_FUTURES[args.contract]
    client_code, token = _load_credentials()
    print(f"=== MCX SILVER probe ({meta['label']}) ===")
    print(f"security_id={meta['security_id']} segment={_EXCHANGE_SEGMENT}")
    print(f"symbol={meta['trading_symbol']} expiry={meta['expiry']}")
    print("(Validation only — does NOT write nifty_ltp_cache.json)\n")

    samples = max(1, args.samples)
    last_ltp: float | None = None
    for i in range(1, samples + 1):
        ltp, status, detail = fetch_ltp(
            client_code=client_code,
            token=token,
            security_id=int(meta["security_id"]),
        )
        print(f"sample {i}/{samples}: http={status} ltp={ltp} ({detail})")
        last_ltp = ltp
        if i < samples:
            time.sleep(2.0)

    if last_ltp is None or last_ltp <= 0:
        print("\nPROBE FAIL: no live LTP")
        return 1
    print(f"\nPROBE OK: live MCX SILVER LTP={last_ltp:,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
