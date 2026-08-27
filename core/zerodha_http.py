"""Optimized Kite Connect v3 REST client for Kavach 2.0 orders.

Persistent httpx session (keepalive + pool), serialized order calls, 429 backoff.
Quotes are last-resort only — ATO LTP stays on the Feeder. No KiteTicker here.
Docs: https://kite.trade/docs/connect/v3/orders/
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("batman.zerodha.http")

KITE_API = "https://api.kite.trade"
KITE_VERSION = "3"

# Kite Connect: ~10 order req/s. Stay under that. Quotes are 1/s.
_ORDER_MIN_INTERVAL_S = 0.12
_QUOTE_MIN_INTERVAL_S = 0.35
_MAX_429_WAIT_S = 30.0


class KiteAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 0, error_type: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class ZerodhaRestClient:
    """One process-wide Kite REST session. Thread-safe."""

    def __init__(self, api_key: str, access_token: str, *, timeout: float = 8.0) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._lock = threading.Lock()
        self._last_order_mono = 0.0
        self._last_quote_mono = 0.0
        self._client = httpx.Client(
            base_url=KITE_API,
            timeout=httpx.Timeout(timeout, connect=min(4.0, timeout)),
            headers=self._headers(),
            http2=False,
            limits=httpx.Limits(
                max_keepalive_connections=8,
                max_connections=16,
                keepalive_expiry=30.0,
            ),
        )

    def _headers(self) -> dict[str, str]:
        return {
            "X-Kite-Version": KITE_VERSION,
            "Authorization": f"token {self._api_key}:{self._access_token}",
        }

    def set_access_token(self, access_token: str) -> None:
        token = (access_token or "").strip()
        if not token:
            return
        with self._lock:
            self._access_token = token
            self._client.headers.update(self._headers())

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _pace(self, *, quote: bool) -> None:
        gap = _QUOTE_MIN_INTERVAL_S if quote else _ORDER_MIN_INTERVAL_S
        key = "_last_quote_mono" if quote else "_last_order_mono"
        now = time.monotonic()
        last = getattr(self, key)
        wait = gap - (now - last)
        if wait > 0:
            time.sleep(wait)
        setattr(self, key, time.monotonic())

    def request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        quote: bool = False,
        timeout: float | None = None,
        raw: bool = False,
    ) -> Any:
        attempts = 4
        last_exc: Exception | None = None
        for attempt in range(attempts):
            with self._lock:
                self._pace(quote=quote)
                try:
                    kwargs: dict[str, Any] = {"headers": self._headers()}
                    if timeout is not None:
                        kwargs["timeout"] = timeout
                    if params:
                        kwargs["params"] = params
                    if data is not None and method.upper() in {"POST", "PUT", "DELETE"}:
                        kwargs["content"] = urlencode(
                            {k: v for k, v in data.items() if v is not None and v != ""}
                        )
                        kwargs["headers"] = {
                            **self._headers(),
                            "Content-Type": "application/x-www-form-urlencoded",
                        }
                    resp = self._client.request(method, path, **kwargs)
                except httpx.HTTPError as exc:
                    last_exc = exc
                    logger.warning("Kite REST transport %s %s: %s", method, path, exc)
                    time.sleep(min(2.0 * (attempt + 1), 8.0))
                    continue

            if resp.status_code == 429:
                wait = min(_MAX_429_WAIT_S, 1.0 * (2**attempt))
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = min(_MAX_429_WAIT_S, max(wait, float(retry_after)))
                    except ValueError:
                        pass
                logger.warning("Kite 429 on %s %s — backoff %.1fs", method, path, wait)
                time.sleep(wait)
                continue

            if raw:
                if resp.status_code >= 400:
                    raise KiteAPIError(
                        f"HTTP {resp.status_code} {path}",
                        status_code=resp.status_code,
                    )
                return resp.content

            try:
                payload = resp.json()
            except Exception as exc:
                raise KiteAPIError(
                    f"Non-JSON Kite response HTTP {resp.status_code}",
                    status_code=resp.status_code,
                ) from exc

            if resp.status_code >= 400 or str(payload.get("status") or "") == "error":
                err_type = str(payload.get("error_type") or "")
                msg = str(payload.get("message") or payload)
                if err_type == "TokenException" or resp.status_code in {403, 401}:
                    raise KiteAPIError(msg, status_code=resp.status_code, error_type="TokenException")
                raise KiteAPIError(msg, status_code=resp.status_code, error_type=err_type)

            return payload.get("data", payload)

        if last_exc:
            raise KiteAPIError(str(last_exc)) from last_exc
        raise KiteAPIError(f"Kite REST failed after retries: {method} {path}")
