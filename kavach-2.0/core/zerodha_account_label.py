"""Cached Zerodha account holder label for the Kavach web desk sidebar.

Fetches Kite /user/profile once per access_token and keeps the result in
process memory. Not used by websocket/state polling.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("batman.zerodha.account_label")

_lock = threading.Lock()
_cache_token: str = ""
_cache: dict[str, str] = {"user_id": "", "name": ""}


def get_zerodha_account_label() -> dict[str, str]:
    """Return {user_id, name} for the current Zerodha access token."""
    global _cache_token, _cache

    from core.zerodha_credentials import load_zerodha_order_creds

    creds = load_zerodha_order_creds()
    token = (creds.access_token or "").strip()
    fallback_uid = (creds.user_id or "").strip()

    with _lock:
        if token and token == _cache_token and (_cache.get("user_id") or _cache.get("name")):
            return dict(_cache)

    if not token or not creds.api_key:
        return {"user_id": fallback_uid, "name": ""}

    user_id = fallback_uid
    name = ""
    try:
        import httpx

        r = httpx.get(
            "https://api.kite.trade/user/profile",
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {creds.api_key}:{token}",
            },
            timeout=15.0,
        )
        if r.status_code == 200:
            body = r.json()
            if body.get("status") == "success":
                data = body.get("data") or {}
                user_id = str(data.get("user_id") or fallback_uid).strip()
                name = str(
                    data.get("user_shortname") or data.get("user_name") or ""
                ).strip()
        else:
            logger.warning(
                "Zerodha profile label HTTP %s — using fallback user_id",
                r.status_code,
            )
    except Exception as exc:
        logger.warning("Zerodha profile label fetch failed: %s", exc)

    out = {"user_id": user_id, "name": name}
    with _lock:
        _cache_token = token
        _cache = dict(out)
    return out
