#!/usr/bin/env python3
"""Smoke: Dhan PIN/TOTP capability + secrets_root mapping (no secret values printed)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from core.batman_mode import secrets_root
    from core.broker import BatmanBroker
    from core.dhan_credentials import dhan_secrets_status
    from core.dhan_pin_totp import pin_totp_env_present

    st = dhan_secrets_status(ROOT)
    print("DHAN PIN/TOTP CAPABILITY SMOKE")
    print(f"  secrets_root     = {secrets_root(ROOT)}")
    print(f"  secrets_file     = {st['secrets_file']}")
    print(f"  candidates       = {st['candidates']}")
    print(f"  keys_present     = {st['keys_present']}")
    print(f"  has_client_code  = {st['has_client_code']}")
    print(f"  has_pin          = {st['has_pin']}")
    print(f"  has_totp_secret  = {st['has_totp_secret']}")
    print(f"  has_access_token = {st['has_access_token']}")
    print(f"  pin_totp_ready   = {st['pin_totp_ready']}")
    print(f"  env_present()    = {pin_totp_env_present(ROOT)}")
    print(f"  broker_api       = {hasattr(BatmanBroker, 'connect_with_pin_totp')}")
    print("  NOTE: Live Dhan login is NOT attempted here.")
    print("  When pin_totp_ready=True, MLG may enable refresh via")
    print("  scripts/refresh_dhan_token_pin_totp.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
