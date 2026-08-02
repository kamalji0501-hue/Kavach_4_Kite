"""Dhan REST marketfeed quotes — no Tradehull session (avoids repeated logins)."""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any

from core.dhan_market_quote import fetch_fno_ltp_rest

_MIN_QUOTE_INTERVAL_SECONDS = 2.0
_quote_lock = threading.Lock()
_last_quote_at: float = 0.0


def fetch_nifty_option_ltps_rest(
    client_code: str,
    access_token: str,
    legs: list[tuple[int, str]],
    *,
    expiry_date: date,
) -> dict[tuple[int, str], float]:
    """Resolve strikes to securityIds, then POST /marketfeed/ltp (NSE_FNO)."""
    from backtest_engine.resolver.instrument_master import (
        load_instrument_master,
        resolve_nifty_option,
    )

    if not legs:
        return {}

    master = load_instrument_master()
    id_to_key: dict[int, tuple[int, str]] = {}
    for strike, opt in legs:
        inst = resolve_nifty_option(
            strike=strike,
            option_type=opt,
            expiry_date=expiry_date,
            master=master,
        )
        id_to_key[int(inst.security_id)] = (int(strike), opt.upper())

    prices = fetch_fno_ltp_rest(client_code, access_token, list(id_to_key))
    return {id_to_key[sid]: px for sid, px in prices.items() if sid in id_to_key}


class DhanRestQuoteClient:
    """Lightweight quote client — REST only, safe to cache on ShadowBroker."""

    def __init__(self, client_code: str, access_token: str) -> None:
        self._client_code = client_code
        self._access_token = access_token
        self._cache: dict[str, tuple[float, Any]] = {}

    def _throttle(self) -> None:
        global _last_quote_at
        with _quote_lock:
            elapsed = time.monotonic() - _last_quote_at
            if elapsed < _MIN_QUOTE_INTERVAL_SECONDS:
                time.sleep(_MIN_QUOTE_INTERVAL_SECONDS - elapsed)
            _last_quote_at = time.monotonic()

    def get_fno_ltp_by_security_ids(self, security_ids: list[int]) -> dict[int, float]:
        key = f"ids:{','.join(map(str, sorted(security_ids)))}"
        cached = self._cache.get(key)
        if cached and (time.monotonic() - cached[0]) < _MIN_QUOTE_INTERVAL_SECONDS:
            return cached[1]
        self._throttle()
        result = fetch_fno_ltp_rest(self._client_code, self._access_token, security_ids)
        self._cache[key] = (time.monotonic(), result)
        return result

    def get_nifty_option_ltps(
        self,
        legs: list[tuple[int, str]],
        *,
        expiry_date: date,
    ) -> dict[tuple[int, str], float]:
        key = f"legs:{expiry_date}:{legs!r}"
        cached = self._cache.get(key)
        if cached and (time.monotonic() - cached[0]) < _MIN_QUOTE_INTERVAL_SECONDS:
            return cached[1]
        self._throttle()
        result = fetch_nifty_option_ltps_rest(
            self._client_code,
            self._access_token,
            legs,
            expiry_date=expiry_date,
        )
        self._cache[key] = (time.monotonic(), result)
        return result


def cached_rest_quote_client(broker: Any) -> DhanRestQuoteClient | None:
    """Return a cached REST quote client on *broker* (no Tradehull)."""
    if broker is None:
        return None
    existing = getattr(broker, "_rest_quote_client", None)
    if isinstance(existing, DhanRestQuoteClient):
        return existing
    cc = getattr(broker, "_client_code", None)
    token = getattr(broker, "_access_token", None)
    if not cc or not token:
        return None
    client = DhanRestQuoteClient(str(cc), str(token))
    try:
        broker._rest_quote_client = client
    except Exception:
        pass
    return client
