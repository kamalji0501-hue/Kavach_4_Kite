"""Runtime WebSocket ↔ REST failover for DRISHTI NIFTY feed.

Persisted ``feed_mode`` in ``data/nifty_ltp_feed_config.json`` is operator-controlled
only (LTP Feed Setup). This module tracks *runtime* active transport:

- Config ``websocket`` → start on WebSocket each trading day.
- WebSocket crash (stale cache after grace OR repeated connection errors) →
  pause ATO, notify operator, switch to REST for the rest of the session.
- REST failure while on fallback → keep retrying; alternate back to WebSocket;
  stay paused until cache is fresh again, then auto-resume ATO.
- Next trading day → try WebSocket again (session lock resets).

See ``telegram/bots/drishti/params.json`` → ``nifty_ltp_feed`` for tunables.
"""

from __future__ import annotations

import logging
import zoneinfo
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from core.nifty_ltp_feed import (
    FEED_MODE_WEBSOCKET,
    NiftyLtpCacheSnapshot,
    NiftyLtpFeedConfig,
)

logger = logging.getLogger("batman.nifty_ltp_failover")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_BOT_DATA_KEY = "nifty_ltp_failover"
_WS_REST_RETRY_SECONDS = 900.0
_WS_REST_RETRY_MAX_PER_DAY = 3


@dataclass
class NiftyFeedFailoverState:
    """In-memory (+ bot_data) runtime transport state — not written to feed config."""

    active_transport: str = "websocket"
    session_rest_lock_date: str | None = None
    degraded: bool = False
    failover_in_progress: bool = False
    last_switch_at: str | None = None
    pause_reason: str | None = None
    ws_retry_count: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> NiftyFeedFailoverState:
        if not raw:
            return cls()
        return cls(
            active_transport=str(raw.get("active_transport", "websocket")),
            session_rest_lock_date=raw.get("session_rest_lock_date"),
            degraded=bool(raw.get("degraded", False)),
            failover_in_progress=bool(raw.get("failover_in_progress", False)),
            last_switch_at=raw.get("last_switch_at"),
            pause_reason=raw.get("pause_reason"),
            ws_retry_count=int(raw.get("ws_retry_count", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _today() -> date:
    return datetime.now(_IST).date()


_DISK_STATE_KEY = "nifty_ltp_failover"


def _load_failover_from_disk() -> NiftyFeedFailoverState | None:
    try:
        from core.batman_mode import state_path, workspace_root
        from core.state import StateManager

        sm = StateManager(path=state_path(workspace_root()))
        raw = sm.get(_DISK_STATE_KEY)
        if isinstance(raw, dict):
            return NiftyFeedFailoverState.from_dict(raw)
    except Exception as exc:
        logger.debug("failover disk load skipped: %s", exc)
    return None


def _persist_failover_to_disk(state: NiftyFeedFailoverState) -> None:
    try:
        from core.batman_mode import state_path, workspace_root
        from core.state import StateManager

        sm = StateManager(path=state_path(workspace_root()))
        sm.set(_DISK_STATE_KEY, state.to_dict())
    except Exception as exc:
        logger.warning("failover state persist failed: %s", exc)


def get_failover_state(bot_data: dict[str, Any]) -> NiftyFeedFailoverState:
    raw = bot_data.get(_BOT_DATA_KEY)
    if isinstance(raw, NiftyFeedFailoverState):
        return raw
    if isinstance(raw, dict):
        state = NiftyFeedFailoverState.from_dict(raw)
        bot_data[_BOT_DATA_KEY] = state
        return state
    disk = _load_failover_from_disk()
    if disk is not None:
        bot_data[_BOT_DATA_KEY] = disk
        return disk
    state = NiftyFeedFailoverState()
    bot_data[_BOT_DATA_KEY] = state
    return state


def save_failover_state(bot_data: dict[str, Any], state: NiftyFeedFailoverState) -> None:
    bot_data[_BOT_DATA_KEY] = state
    _persist_failover_to_disk(state)


def reset_failover_for_new_session(bot_data: dict[str, Any], *, today: date | None = None) -> bool:
    """Clear session REST lock when the calendar day changes."""
    today = today or _today()
    state = get_failover_state(bot_data)
    if state.session_rest_lock_date is None:
        return False
    if state.session_rest_lock_date == today.isoformat():
        return False
    state.session_rest_lock_date = None
    state.active_transport = "websocket"
    state.degraded = False
    state.failover_in_progress = False
    state.pause_reason = None
    state.ws_retry_count = 0
    save_failover_state(bot_data, state)
    logger.info("NIFTY failover session reset — will prefer WebSocket on %s", today)
    return True


def apply_operator_transport_choice(bot_data: dict[str, Any], mode: str) -> None:
    """Honor LTP Feed Setup choice — clears sticky same-day REST failover lock.

    Without this, selecting WebSocket only rewrote ``nifty_ltp_feed_config.json``
    while ``session_rest_lock_date`` kept ``resolve_active_transport`` on REST.
    """
    mode = str(mode or "").strip().lower()
    state = get_failover_state(bot_data)
    if mode == "websocket":
        state.active_transport = "websocket"
        state.session_rest_lock_date = None
        state.degraded = False
        state.failover_in_progress = False
        state.pause_reason = None
        state.ws_retry_count = 0
        state.last_switch_at = datetime.now(_IST).isoformat()
        save_failover_state(bot_data, state)
        logger.info("NIFTY operator chose WebSocket — cleared REST failover lock")
        return
    if mode == "rest":
        state.active_transport = "rest"
        state.session_rest_lock_date = None
        state.degraded = False
        state.failover_in_progress = False
        state.pause_reason = None
        state.last_switch_at = datetime.now(_IST).isoformat()
        save_failover_state(bot_data, state)
        logger.info("NIFTY operator chose REST — runtime transport set to REST")


def _websocket_retry_due(state: NiftyFeedFailoverState) -> bool:
    if state.ws_retry_count >= _WS_REST_RETRY_MAX_PER_DAY:
        return False
    if state.last_switch_at is None:
        return False
    try:
        last = datetime.fromisoformat(state.last_switch_at)
        if last.tzinfo is None:
            last = last.replace(tzinfo=_IST)
    except (TypeError, ValueError):
        return False
    elapsed = (datetime.now(_IST) - last.astimezone(_IST)).total_seconds()
    return elapsed >= _WS_REST_RETRY_SECONDS


def try_websocket_retry_after_rest(bot_data: dict[str, Any]) -> bool:
    """After REST fallback stabilizes, retry WebSocket (up to 3× per session)."""
    state = get_failover_state(bot_data)
    if state.active_transport != "rest":
        return False
    if state.session_rest_lock_date != _today().isoformat():
        return False
    if not _websocket_retry_due(state):
        return False
    state.session_rest_lock_date = None
    state.active_transport = "websocket"
    state.degraded = True
    state.ws_retry_count += 1
    state.last_switch_at = datetime.now(_IST).isoformat()
    save_failover_state(bot_data, state)
    logger.info(
        "NIFTY failover: WebSocket retry #%s after REST stabilization",
        state.ws_retry_count,
    )
    return True


def resolve_active_transport(
    cfg: NiftyLtpFeedConfig,
    bot_data: dict[str, Any],
    *,
    today: date | None = None,
) -> str:
    """Return ``websocket`` or ``rest`` for in-process collectors (not external WS)."""
    today = today or _today()
    if not cfg.is_websocket_mode():
        if cfg.is_rest_mode():
            return "rest"
        return cfg.feed_mode

    reset_failover_for_new_session(bot_data, today=today)
    state = get_failover_state(bot_data)

    # While degraded, honor the alternating transport (WS ↔ REST recovery).
    if state.degraded and state.active_transport in ("websocket", "rest"):
        return state.active_transport
    # Same-day auto-failover lock keeps REST until next day or operator override.
    if state.session_rest_lock_date == today.isoformat():
        return "rest"
    # Config is websocket and no session lock — always prefer WS (ignore stale
    # active_transport=rest left behind after a partial clear / restart).
    return "websocket"


def cache_transport_label(snap: NiftyLtpCacheSnapshot | None) -> str:
    """Display label from cache writer source (not configured mode)."""
    if snap is None:
        return "Cache — unknown"
    src = (snap.source or "").lower()
    if "uat_replay" in src or src == "uat":
        return "Cache — UAT Replay"
    if "websocket" in src:
        return "Cache — WebSocket"
    if "rest" in src:
        return "Cache — REST"
    return "Cache — unknown"


def live_transport_label(transport: str) -> str:
    if transport == "websocket":
        return "Live — WebSocket"
    if transport == "rest":
        return "Live — REST"
    return f"Live — {transport}"


def active_transport_label(cfg: NiftyLtpFeedConfig, bot_data: dict[str, Any]) -> str:
    transport = resolve_active_transport(cfg, bot_data)
    if transport == "websocket":
        return "WebSocket"
    if transport == "rest" and cfg.is_websocket_mode():
        return "REST (fallback)"
    return "REST"


def is_failover_eligible(cfg: NiftyLtpFeedConfig | None) -> bool:
    return cfg is not None and cfg.feed_mode == FEED_MODE_WEBSOCKET
