"""Dhan marketfeed/ltp — index and NSE F&O option quotes by securityId."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.exceptions import BrokerConnectionError
from core.nifty_ltp import _DHAN_LTP_URL, _extract_dhan_error, is_rate_limit_error

logger = logging.getLogger("batman.dhan_market_quote")


def _segment_ltp_map(payload: dict[str, Any], segment: str) -> dict[str, dict[str, Any]]:
    """Return securityId → quote dict from marketfeed/ltp JSON."""
    outer = payload.get("data")
    if not isinstance(outer, dict):
        return {}

    blocks: list[dict[str, Any]] = [outer]
    nested = outer.get("data")
    if isinstance(nested, dict):
        blocks.append(nested)

    for block in blocks:
        seg = block.get(segment)
        if isinstance(seg, dict):
            return {str(k): v for k, v in seg.items() if isinstance(v, dict)}
    return {}


def parse_marketfeed_ltp(
    payload: dict[str, Any],
    segment: str,
    security_ids: list[int],
) -> dict[int, float]:
    """Parse last_price for each security id in a marketfeed/ltp response."""
    seg_map = _segment_ltp_map(payload, segment)
    out: dict[int, float] = {}
    for sid in security_ids:
        raw = seg_map.get(str(sid)) or seg_map.get(str(int(sid)))
        if not isinstance(raw, dict):
            continue
        last_price = raw.get("last_price")
        if last_price is None:
            continue
        try:
            px = float(last_price)
        except (TypeError, ValueError):
            continue
        if px > 0:
            out[int(sid)] = round(px, 2)
    return out


def fetch_marketfeed_ltp_rest(
    client_code: str,
    access_token: str,
    securities: dict[str, list[int]],
    *,
    timeout: float = 15.0,
) -> dict[str, dict[int, float]]:
    """POST /marketfeed/ltp for one or more segments.

    Example body: ``{"IDX_I": [13], "NSE_FNO": [42259, 42261]}``.
    Returns ``{segment: {security_id: last_price}}``.
    """
    if not access_token:
        raise BrokerConnectionError("access_token is empty")
    if not securities:
        return {}

    body = {seg: [int(x) for x in ids] for seg, ids in securities.items() if ids}
    response = httpx.post(
        _DHAN_LTP_URL,
        headers={
            "access-token": access_token,
            "client-id": client_code,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    if response.status_code == 429:
        raise BrokerConnectionError(
            f"Too many requests (HTTP 429). {_extract_dhan_error(response)}"
        )
    if response.status_code != 200:
        raise BrokerConnectionError(_extract_dhan_error(response))

    payload = response.json()
    if str(payload.get("status", "")).lower() == "failure":
        raise BrokerConnectionError(f"marketfeed/ltp failed: {payload}")

    result: dict[str, dict[int, float]] = {}
    for segment, ids in body.items():
        parsed = parse_marketfeed_ltp(payload, segment, ids)
        if parsed:
            result[segment] = parsed
    return result


def fetch_fno_ltp_rest(
    client_code: str,
    access_token: str,
    security_ids: list[int],
) -> dict[int, float]:
    """Last traded prices for NSE F&O contracts by Dhan securityId."""
    if not security_ids:
        return {}
    try:
        data = fetch_marketfeed_ltp_rest(
            client_code,
            access_token,
            {"NSE_FNO": security_ids},
        )
    except BrokerConnectionError:
        raise
    except Exception as exc:
        if is_rate_limit_error(str(exc)):
            raise BrokerConnectionError(str(exc)) from exc
        raise BrokerConnectionError(f"FNO LTP fetch failed: {exc}") from exc
    return data.get("NSE_FNO", {})
