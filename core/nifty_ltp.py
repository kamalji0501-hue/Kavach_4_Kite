"""NIFTY LTP fetch via Dhan websocket v2 (Phase 1 reference pattern)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from core.dhan_ws_tick import extract_ltp_from_ws_tick
from core.exceptions import BrokerAuthError, BrokerConnectionError

logger = logging.getLogger("batman.nifty_ltp")

_NIFTY_INSTRUMENT = (0, "13", 15)
_DHAN_FUND_LIMIT_URL = "https://api.dhan.co/v2/fundlimit"
_DHAN_LTP_URL = "https://api.dhan.co/v2/marketfeed/ltp"
_NIFTY_SECURITY_ID = 13


def _parse_nifty_ltp_from_marketfeed_payload(payload: dict[str, Any]) -> float:
    """Parse NIFTY last_price from Dhan marketfeed/ltp JSON (supports both response shapes)."""
    outer = payload.get("data")
    if not isinstance(outer, dict):
        raise BrokerConnectionError(f"NIFTY LTP missing from REST response: {payload}")

    # Live API (2026): {"data": {"IDX_I": {"13": {...}}}, "status": "success"}
    # Some docs/samples: {"data": {"data": {"IDX_I": {"13": {...}}}}}
    candidates: list[dict[str, Any]] = [outer]
    nested = outer.get("data")
    if isinstance(nested, dict):
        candidates.append(nested)

    quote: dict[str, Any] | None = None
    for block in candidates:
        idx_data = block.get("IDX_I")
        if not isinstance(idx_data, dict):
            continue
        raw = idx_data.get(str(_NIFTY_SECURITY_ID)) or idx_data.get(_NIFTY_SECURITY_ID)
        if isinstance(raw, dict):
            quote = raw
            break

    if not quote:
        raise BrokerConnectionError(f"NIFTY LTP missing from REST response: {payload}")

    last_price = quote.get("last_price")
    if last_price is None:
        raise BrokerConnectionError(f"NIFTY last_price missing from REST response: {quote}")
    ltp = float(last_price)
    if ltp <= 0:
        raise BrokerConnectionError(f"Non-positive NIFTY LTP from REST: {ltp}")
    return ltp


def _extract_dhan_error(response: httpx.Response) -> str:
    detail = response.text.strip()
    try:
        payload = response.json()
        data = payload.get("data")
        if isinstance(data, dict):
            return " | ".join(str(v) for v in data.values()) or detail
        if isinstance(data, str):
            return data
        detail = (
            payload.get("errorMessage") or payload.get("remarks", {}).get("error_message") or detail
        )
    except Exception:
        pass
    return str(detail)[:240]


def validate_dhan_access_token(client_code: str, access_token: str) -> tuple[bool, str]:
    """Return (ok, error_message). Uses Dhan fundlimit as a lightweight auth probe."""
    if not client_code or not access_token:
        return False, "Client ID or access token is missing."

    try:
        response = httpx.get(
            _DHAN_FUND_LIMIT_URL,
            headers={"access-token": access_token, "client-id": client_code},
            timeout=15.0,
        )
    except Exception as exc:
        return False, f"Could not reach Dhan API: {exc}"

    if response.status_code == 200:
        return True, ""

    return False, _extract_dhan_error(response)


def check_market_data_subscription(client_code: str, access_token: str) -> tuple[bool, str]:
    """Return (ok, error_message). Probes Dhan LTP API for market-data entitlement."""
    if not client_code or not access_token:
        return False, "Client ID or access token is missing."

    try:
        response = httpx.post(
            _DHAN_LTP_URL,
            headers={
                "access-token": access_token,
                "client-id": client_code,
                "Content-Type": "application/json",
            },
            json={"IDX_I": [_NIFTY_SECURITY_ID]},
            timeout=15.0,
        )
    except Exception as exc:
        return False, f"Could not reach Dhan market data API: {exc}"

    if response.status_code == 200:
        return True, ""

    detail = _extract_dhan_error(response)
    lowered = detail.lower()
    if "not subscribed" in lowered or "806" in detail:
        return False, (
            "Dhan Data APIs are not subscribed on your account. "
            "Enable market data in Dhan → Profile → Access DhanHQ APIs / Data subscription, "
            "then paste a fresh JWT via Update Token."
        )
    return False, detail


def is_rate_limit_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "429" in lowered
        or "too many requests" in lowered
        or "rate limit" in lowered
        or "throttle" in lowered
    )


def is_auth_error(message: str) -> bool:
    """True for Dhan JWT/auth failures — do not retry or WS↔REST failover."""
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "401",
            "403",
            "unauthorized",
            "invalid token",
            "invalid access",
            "access-token",
            "authentication",
            "auth failed",
            "jwt expired",
            "token expired",
            "token invalid",
            "invalid jwt",
        )
    )


def fetch_nifty_ltp_rest(client_code: str, access_token: str) -> float:
    """Fetch NIFTY LTP via Dhan REST marketfeed when websocket is unavailable."""
    response = httpx.post(
        _DHAN_LTP_URL,
        headers={
            "access-token": access_token,
            "client-id": client_code,
            "Content-Type": "application/json",
        },
        json={"IDX_I": [_NIFTY_SECURITY_ID]},
        timeout=15.0,
    )
    if response.status_code == 429:
        raise BrokerConnectionError(
            f"Too many requests (HTTP 429). {_extract_dhan_error(response)}"
        )
    if response.status_code in (401, 403):
        raise BrokerAuthError(
            f"Dhan rejected the access token (HTTP {response.status_code}). "
            f"{_extract_dhan_error(response)}"
        )
    if response.status_code != 200:
        detail = _extract_dhan_error(response)
        if is_auth_error(detail):
            raise BrokerAuthError(detail)
        raise BrokerConnectionError(detail)

    payload = response.json()
    return _parse_nifty_ltp_from_marketfeed_payload(payload)


def fetch_nifty_ltp_rest_with_retry(
    client_code: str,
    access_token: str,
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    backoff_multiplier: float = 2.0,
    rate_limit_extra_seconds: float = 10.0,
) -> float:
    """REST LTP with exponential backoff; longer pauses on Dhan rate limits."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fetch_nifty_ltp_rest(client_code, access_token)
        except BrokerAuthError:
            raise
        except BrokerConnectionError as exc:
            last_exc = exc
            if attempt >= max_attempts - 1:
                break
            msg = str(exc)
            if is_rate_limit_error(msg):
                delay = rate_limit_extra_seconds * (backoff_multiplier**attempt)
            else:
                delay = base_delay_seconds * (backoff_multiplier**attempt)
            logger.warning(
                "NIFTY REST LTP retry %s/%s in %.1fs: %s",
                attempt + 1,
                max_attempts,
                delay,
                msg[:120],
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc


async def _fetch_single_tick(feed: Any, timeout_seconds: float) -> dict[str, Any]:
    await feed.connect()
    return await asyncio.wait_for(feed.get_instrument_data(), timeout=timeout_seconds)


async def _disconnect_feed(feed: Any) -> None:
    try:
        if hasattr(feed, "disconnect"):
            await feed.disconnect()
        elif hasattr(feed, "close"):
            await feed.close()
    except Exception:
        pass


async def fetch_nifty_ltp_websocket(
    client_code: str,
    access_token: str,
    *,
    timeout_seconds: float = 30.0,
    max_retries: int = 3,
    skip_auth_checks: bool = False,
) -> float:
    """Fetch one NIFTY tick via Dhan market feed websocket v2."""
    try:
        from dhanhq import DhanContext
        from dhanhq.marketfeed import MarketFeed
    except ImportError as exc:
        raise BrokerConnectionError(
            "dhanhq package not installed. Run: pip install dhanhq==2.2.0rc1"
        ) from exc

    if not skip_auth_checks:
        ok, auth_error = validate_dhan_access_token(client_code, access_token)
        if not ok:
            raise BrokerAuthError(
                auth_error or "Dhan rejected the access token. Paste a fresh JWT via Update Token."
            )

        subscribed, sub_error = check_market_data_subscription(client_code, access_token)
        if not subscribed:
            raise BrokerAuthError(sub_error)

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        feed = None
        try:
            context = DhanContext(client_id=client_code, access_token=access_token)
            feed = MarketFeed(
                dhan_context=context,
                instruments=[_NIFTY_INSTRUMENT],
                version="v2",
            )
            tick = await _fetch_single_tick(feed, timeout_seconds=timeout_seconds)
            deadline = time.monotonic() + timeout_seconds
            ltp = extract_ltp_from_ws_tick(tick)
            while ltp is None:
                if time.monotonic() >= deadline:
                    raise BrokerConnectionError(f"LTP missing in websocket tick: {tick}")
                tick = await asyncio.wait_for(
                    feed.get_instrument_data(),
                    timeout=max(1.0, deadline - time.monotonic()),
                )
                ltp = extract_ltp_from_ws_tick(tick)
            return ltp
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                wait_s = 2**attempt
                logger.warning(
                    "NIFTY websocket LTP attempt %s/%s failed: %s",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                await asyncio.sleep(wait_s)
        finally:
            if feed is not None:
                await _disconnect_feed(feed)

    raise BrokerConnectionError(
        f"NIFTY LTP websocket fetch failed after {max_retries + 1} attempts: {last_error}"
    ) from last_error


async def fetch_nifty_ltp(
    client_code: str,
    access_token: str,
    *,
    timeout_seconds: float = 30.0,
    max_retries: int = 3,
) -> tuple[float, str]:
    """Fetch NIFTY LTP; returns (price, source_label).

    Primary: Dhan WebSocket v2. REST marketfeed/ltp is fallback on WS failure.
    """
    ok, auth_error = validate_dhan_access_token(client_code, access_token)
    if not ok:
        raise BrokerAuthError(
            auth_error or "Dhan rejected the access token. Paste a fresh JWT via Update Token."
        )

    subscribed, sub_error = check_market_data_subscription(client_code, access_token)
    if not subscribed:
        raise BrokerAuthError(sub_error)

    try:
        ltp = await fetch_nifty_ltp_websocket(
            client_code,
            access_token,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            skip_auth_checks=True,
        )
        return ltp, "Dhan websocket v2"
    except BrokerConnectionError as exc:
        logger.warning("Websocket LTP failed, trying REST fallback: %s", exc)
        ltp = await asyncio.to_thread(
            fetch_nifty_ltp_rest_with_retry,
            client_code,
            access_token,
            max_attempts=max_retries,
            base_delay_seconds=1.0,
            backoff_multiplier=2.0,
        )
        return ltp, "Dhan REST marketfeed"
