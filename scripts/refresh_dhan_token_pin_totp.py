#!/usr/bin/env python3
"""Refresh Dhan JWT in TokenStore using PIN/TOTP env credentials.

Never prints or persists PIN / TOTP seed — only the resulting access token.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.batman_mode import access_token_path, ensure_runtime_layout
from core.dhan_credentials import apply_dhan_secrets_env, dhan_secrets_status
from core.dhan_pin_totp import obtain_access_token_via_pin_totp, pin_totp_env_present
from core.token_store import TokenStore


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("refresh_dhan_token_pin_totp")
    ensure_runtime_layout(ROOT)
    loaded = apply_dhan_secrets_env(ROOT)
    st = dhan_secrets_status(ROOT)
    log.info("Dhan secrets file=%s pin_totp_ready=%s", loaded, st.get("pin_totp_ready"))

    if not pin_totp_env_present():
        log.error("Set DHAN_PIN and DHAN_TOTP_SECRET in the runtime secrets .env (not in git).")
        return 2

    client, token = obtain_access_token_via_pin_totp()
    store = TokenStore(path=access_token_path(ROOT))
    store.save(token)
    legacy = TokenStore(path=ROOT / "data" / "access_token.json")
    try:
        legacy.save(token)
    except Exception:
        pass
    log.info("Saved JWT for client=%s into TokenStore (token length=%s). PIN/TOTP not stored.", client, len(token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
