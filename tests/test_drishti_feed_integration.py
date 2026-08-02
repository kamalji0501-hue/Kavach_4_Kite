"""Tests for DRISHTI NIFTY cache-only button logic (no duplicate Dhan connections)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from bat_telegram.bots.drishti.nifty_feed_integration import (
    format_cache_ltp_reply,
    format_feed_status_line,
    nifty_feed_token_block_reason,
    rest_method_disabled_message,
    websocket_method_disabled_message,
)
from core.nifty_ltp_failover import NiftyFeedFailoverState, cache_transport_label
from core.nifty_ltp_feed import (
    FEED_MODE_REST,
    FEED_MODE_WEBSOCKET,
    NiftyLtpCacheSnapshot,
    NiftyLtpFeedConfig,
)
from core.token_store import TokenStore

_IST = ZoneInfo("Asia/Kolkata")


def _card(ltp: float, source: str, ts: str | None = None) -> str:
    return f"PRICE={ltp}|SRC={source}|TS={ts}"


def test_format_cache_fresh_snapshot() -> None:
    now = datetime.now(_IST).isoformat()
    snap = NiftyLtpCacheSnapshot(
        ltp=23500.0,
        updated_at=now,
        last_changed_at=now,
        source="dhan_websocket",
        feed_healthy=True,
        poll_interval_seconds=2,
    )
    cfg = NiftyLtpFeedConfig(
        feed_mode=FEED_MODE_WEBSOCKET,
        poll_interval_seconds=2,
        stale_price_alert_seconds=10,
    )
    text = format_cache_ltp_reply(
        snap,
        cfg,
        feed_running=True,
        format_ltp_card=_card,
        in_market_session=True,
    )
    assert "23500" in text
    assert "healthy" in text
    assert cache_transport_label(snap) in text


def test_format_cache_shows_rest_fallback_when_degraded() -> None:
    now = datetime.now(_IST).isoformat()
    snap = NiftyLtpCacheSnapshot(
        ltp=23500.0,
        updated_at=now,
        last_changed_at=now,
        source="dhan_rest",
        feed_healthy=True,
        poll_interval_seconds=2,
    )
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET, poll_interval_seconds=2)
    bot_data = {
        "nifty_ltp_failover": NiftyFeedFailoverState(
            active_transport="rest",
            session_rest_lock_date=datetime.now(_IST).date().isoformat(),
            degraded=True,
        )
    }
    text = format_cache_ltp_reply(
        snap,
        cfg,
        feed_running=True,
        format_ltp_card=_card,
        in_market_session=True,
        bot_data=bot_data,
    )
    assert "REST (fallback)" in text
    assert "Cache — REST" in text


def test_format_cache_stale_still_shows_price() -> None:
    old = datetime.now(_IST).replace(hour=9, minute=0, second=0).isoformat()
    snap = NiftyLtpCacheSnapshot(
        ltp=23400.0,
        updated_at=old,
        last_changed_at=old,
        feed_healthy=False,
        poll_interval_seconds=2,
    )
    cfg = NiftyLtpFeedConfig(poll_interval_seconds=2, stale_price_alert_seconds=10)
    text = format_cache_ltp_reply(
        snap,
        cfg,
        feed_running=True,
        format_ltp_card=_card,
        in_market_session=True,
    )
    assert "23400" in text
    assert "stale" in text.lower() or "may be stale" in text.lower()
    assert "Live Price" in text


def test_format_cache_off_hours_shows_last_snapshot() -> None:
    now = datetime.now(_IST).isoformat()
    snap = NiftyLtpCacheSnapshot(
        ltp=23497.15,
        updated_at=now,
        last_changed_at=now,
        feed_healthy=True,
        poll_interval_seconds=2,
    )
    cfg = NiftyLtpFeedConfig(poll_interval_seconds=2, stale_price_alert_seconds=10)
    text = format_cache_ltp_reply(
        snap,
        cfg,
        feed_running=True,
        format_ltp_card=_card,
        in_market_session=False,
    )
    assert "23497" in text
    assert "Market closed" in text


def test_format_cache_warming_up_when_no_cache() -> None:
    cfg = NiftyLtpFeedConfig(
        feed_mode=FEED_MODE_WEBSOCKET,
        poll_interval_seconds=2,
        stale_price_alert_seconds=10,
    )
    text = format_cache_ltp_reply(
        None,
        cfg,
        feed_running=True,
        format_ltp_card=_card,
        in_market_session=True,
    )
    assert "warming" in text.lower() or "cache" in text.lower()


def test_mode_disabled_messages() -> None:
    ws_cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET)
    rest_cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_REST)
    assert "REST method is not enabled" in rest_method_disabled_message(ws_cfg)
    assert "websocket" in websocket_method_disabled_message(rest_cfg).lower()


def test_format_feed_status_line_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        "bat_telegram.bots.drishti.nifty_feed_integration.load_feed_config",
        lambda path=None: None,
    )
    line = format_feed_status_line()
    assert "not configured" in line


def test_expired_token_blocks_feed_reason(tmp_path) -> None:
    store = TokenStore(path=tmp_path / "access_token.json")
    store.save("dummy.jwt.token")
    from unittest.mock import patch

    with patch("core.token_store.TokenStore.is_effectively_expired", return_value=True):
        reason = nifty_feed_token_block_reason(store)
    assert reason is not None
    assert "expired" in reason.lower()
    assert "update token" in reason.lower()
