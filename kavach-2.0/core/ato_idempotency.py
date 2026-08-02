"""ATO order idempotency keys — prevent duplicate CE/PE protect orders on retry."""

from __future__ import annotations

import zoneinfo
from datetime import datetime
from typing import Any

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_STATE_PREFIX = "ato.idempotency."


def ato_order_key(side: str, action: str, symbol: str, *, date_ist: str | None = None) -> str:
    """Stable key: ``YYYY-MM-DD:CE:BUY:NIFTY-...``."""
    day = date_ist or datetime.now(_IST).date().isoformat()
    return f"{day}:{side.upper()}:{action.upper()}:{symbol}"


def get_existing_ato_order(state: Any, key: str) -> str | None:
    if state is None:
        return None
    val = state.get(f"{_STATE_PREFIX}{key}")
    return str(val) if val else None


def record_ato_order(state: Any, key: str, order_id: str) -> None:
    if state is None:
        return
    state.set(f"{_STATE_PREFIX}{key}", str(order_id), save=False)


def clear_ato_order(state: Any, key: str) -> None:
    """Drop an idempotency key so the next ATO cycle can place again."""
    if state is None:
        return
    state.set(f"{_STATE_PREFIX}{key}", None, save=False)


def clear_side_cycle_keys(state: Any, side: str, symbol: str) -> None:
    """Clear BUY+SELL keys for a side/symbol (after exit or stale recovery)."""
    if state is None or not symbol:
        return
    for action in ("BUY", "SELL"):
        clear_ato_order(state, ato_order_key(side, action, symbol))
