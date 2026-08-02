"""Tests for runtime NIFTY WS↔REST failover state."""

from __future__ import annotations

from datetime import date

from core.nifty_ltp_failover import (
    NiftyFeedFailoverState,
    cache_transport_label,
    live_transport_label,
    reset_failover_for_new_session,
    resolve_active_transport,
    save_failover_state,
)
from core.nifty_ltp_feed import FEED_MODE_WEBSOCKET, NiftyLtpCacheSnapshot, NiftyLtpFeedConfig


def test_resolve_prefers_websocket_on_fresh_session() -> None:
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET)
    bot_data: dict = {}
    assert resolve_active_transport(cfg, bot_data, today=date(2026, 6, 7)) == "websocket"


def test_session_rest_lock_stays_on_rest_until_new_day() -> None:
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET)
    bot_data: dict = {}
    state = NiftyFeedFailoverState(
        active_transport="rest",
        session_rest_lock_date="2026-06-07",
    )
    save_failover_state(bot_data, state)
    assert resolve_active_transport(cfg, bot_data, today=date(2026, 6, 7)) == "rest"


def test_degraded_alternate_overrides_session_lock() -> None:
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET)
    bot_data: dict = {}
    state = NiftyFeedFailoverState(
        active_transport="websocket",
        session_rest_lock_date="2026-06-07",
        degraded=True,
    )
    save_failover_state(bot_data, state)
    assert resolve_active_transport(cfg, bot_data, today=date(2026, 6, 7)) == "websocket"


def test_reset_failover_on_new_trading_day() -> None:
    bot_data: dict = {}
    state = NiftyFeedFailoverState(
        active_transport="rest",
        session_rest_lock_date="2026-06-06",
        degraded=True,
    )
    save_failover_state(bot_data, state)
    assert reset_failover_for_new_session(bot_data, today=date(2026, 6, 7)) is True
    assert resolve_active_transport(
        NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET),
        bot_data,
        today=date(2026, 6, 7),
    ) == "websocket"


def test_cache_and_live_labels() -> None:
    ts = "2026-06-07T10:00:00+05:30"
    ws_snap = NiftyLtpCacheSnapshot(
        ltp=1.0, updated_at=ts, last_changed_at=ts, source="dhan_websocket"
    )
    rest_snap = NiftyLtpCacheSnapshot(
        ltp=1.0, updated_at=ts, last_changed_at=ts, source="dhan_rest"
    )
    assert cache_transport_label(ws_snap) == "Cache — WebSocket"
    assert cache_transport_label(rest_snap) == "Cache — REST"
    assert live_transport_label("websocket") == "Live — WebSocket"
    assert live_transport_label("rest") == "Live — REST"


def test_failover_state_persists_to_batman_state(tmp_path, monkeypatch) -> None:
    from core.nifty_ltp_failover import get_failover_state
    from core.state import StateManager

    state_file = tmp_path / "batman_state.json"
    state_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("core.batman_mode.state_path", lambda root=None: state_file)
    monkeypatch.setattr("core.batman_mode.workspace_root", lambda: tmp_path)

    bot_data: dict = {}
    state = NiftyFeedFailoverState(
        active_transport="rest",
        session_rest_lock_date="2026-06-12",
        degraded=True,
    )
    save_failover_state(bot_data, state)

    sm = StateManager(path=state_file)
    raw = sm.get("nifty_ltp_failover")
    assert isinstance(raw, dict)
    assert raw["active_transport"] == "rest"

    loaded = get_failover_state({})
    assert loaded.active_transport == "rest"
    assert loaded.session_rest_lock_date == "2026-06-12"


def test_websocket_retry_after_rest(monkeypatch) -> None:
    from datetime import datetime, timedelta

    import core.nifty_ltp_failover as nf
    from core.nifty_ltp_failover import (
        NiftyFeedFailoverState,
        resolve_active_transport,
        try_websocket_retry_after_rest,
    )

    monkeypatch.setattr(nf, "_WS_REST_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(nf, "_today", lambda: date(2026, 6, 12))
    bot_data: dict = {}
    state = NiftyFeedFailoverState(
        active_transport="rest",
        session_rest_lock_date="2026-06-12",
        last_switch_at=(datetime.now(nf._IST) - timedelta(minutes=20)).isoformat(),
        ws_retry_count=0,
    )
    save_failover_state(bot_data, state)
    assert try_websocket_retry_after_rest(bot_data) is True
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET)
    assert resolve_active_transport(cfg, bot_data, today=date(2026, 6, 12)) == "websocket"
