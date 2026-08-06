"""Paper / Live trade lane logging.

Prefixes human log lines so operators can tell paper vs live at a glance:

  ... INFO [PAPER TRADE] batman.order_manager: ...
  ... INFO [LIVE TRADE] batman.order_manager: ...

Also used by money_audit JSONL via ``trade_lane`` field + ``money_audit_paper.jsonl``.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Literal

TradeLane = Literal["paper", "live", "unknown"]

_TRADE_LANE: ContextVar[TradeLane] = ContextVar("batman_trade_lane", default="unknown")

PAPER_PREFIX = "[PAPER TRADE]"
LIVE_PREFIX = "[LIVE TRADE]"


def set_trade_lane(lane: str | None) -> None:
    raw = (lane or "").strip().lower()
    if raw == "paper":
        _TRADE_LANE.set("paper")
    elif raw == "live":
        _TRADE_LANE.set("live")
    else:
        _TRADE_LANE.set("unknown")


def get_trade_lane() -> TradeLane:
    try:
        return _TRADE_LANE.get()
    except LookupError:
        return "unknown"


def trade_lane_prefix(lane: str | None = None) -> str:
    lane_s = (lane or get_trade_lane()).strip().lower()
    if lane_s == "paper":
        return PAPER_PREFIX
    if lane_s == "live":
        return LIVE_PREFIX
    return ""


def apply_message_prefix(message: str, lane: str | None = None) -> str:
    """Prefix message once for the active/override lane."""
    msg = str(message)
    pref = trade_lane_prefix(lane)
    if not pref or pref in msg:
        return msg
    return f"{pref} {msg}"


class TradeLaneFormatter(logging.Formatter):
    """Formatter that injects [PAPER TRADE] / [LIVE TRADE] after level name."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        lane = getattr(record, "trade_lane", None) or get_trade_lane()
        pref = trade_lane_prefix(lane)
        if not pref or pref in formatted:
            return formatted
        # Insert after levelname token when present
        token = f"{record.levelname} "
        if token in formatted:
            return formatted.replace(token, f"{token}{pref} ", 1)
        return f"{pref} {formatted}"
