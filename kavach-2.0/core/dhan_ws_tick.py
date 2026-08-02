"""Parse Dhan market-feed websocket v2 tick payloads.

Dhan v2 may send control frames before live LTP ticks, e.g. ``Previous Close``
(with ``prev_close``, no ``LTP`` key). These must be skipped — not treated as errors.
"""

from __future__ import annotations

from typing import Any

# Known non-LTP frame types from Dhan marketfeed v2 (skip silently).
_DHAN_WS_CONTROL_TYPES = frozenset({"Previous Close"})


def is_dhan_ws_control_tick(tick: Any) -> bool:
    """True for Dhan control/metadata frames that are not live LTP updates."""
    if not isinstance(tick, dict):
        return False
    tick_type = tick.get("type")
    return isinstance(tick_type, str) and tick_type in _DHAN_WS_CONTROL_TYPES


def extract_ltp_from_ws_tick(tick: Any) -> float | None:
    """Return LTP from a tick; None for control frames (e.g. Previous Close)."""
    if not isinstance(tick, dict):
        return None
    if "LTP" not in tick:
        return None
    try:
        ltp = float(tick["LTP"])
    except (TypeError, ValueError):
        return None
    return ltp if ltp > 0 else None
