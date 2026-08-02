"""Unit + integration tests for MarketDataProvider strategy and UAT wiring."""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bat_telegram.bots.drishti.nifty_feed_integration import uat_button_disabled_message
from core.market_data_provider import (
    LIVE_LOG_TAG,
    LiveMarketProvider,
    MarketDataMode,
    ReplayMarketProvider,
    build_market_data_provider,
    live_feed_should_run,
    select_market_data_mode,
)
from core.nifty_ltp_feed import NiftyLtpCacheSnapshot, write_nifty_ltp_cache
from core.nifty_ltp_uat_replay import (
    UAT_LOG_TAG,
    NiftyLtpUatReplayConfig,
    is_drishti_uat_replay_window,
)

_IST = ZoneInfo("Asia/Kolkata")


def test_force_uat_mode_overrides_market_hours() -> None:
    cfg = NiftyLtpUatReplayConfig(force_uat_mode=True)
    session = datetime(2026, 7, 16, 10, 30, tzinfo=_IST)
    assert is_drishti_uat_replay_window(session, config=cfg) is True
    assert select_market_data_mode(cfg, now=session) is MarketDataMode.UAT_REPLAY
    assert live_feed_should_run(cfg) is False


def test_select_live_during_market_hours() -> None:
    cfg = NiftyLtpUatReplayConfig(force_uat_mode=False)
    session = datetime(2026, 7, 16, 10, 30, tzinfo=_IST)
    assert select_market_data_mode(cfg, now=session) is MarketDataMode.LIVE
    assert isinstance(build_market_data_provider(cfg, now=session), LiveMarketProvider)


def test_select_uat_after_hours() -> None:
    cfg = NiftyLtpUatReplayConfig()
    evening = datetime(2026, 7, 16, 18, 0, tzinfo=_IST)
    assert select_market_data_mode(cfg, now=evening) is MarketDataMode.UAT_REPLAY
    assert isinstance(build_market_data_provider(cfg, now=evening), ReplayMarketProvider)


def test_provider_get_nifty_ltp_reads_shared_cache(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "nifty_ltp_cache.json"
    now = datetime.now(_IST)
    write_nifty_ltp_cache(
        NiftyLtpCacheSnapshot(
            ltp=25123.45,
            updated_at=now.isoformat(),
            last_changed_at=now.isoformat(),
            source="uat_replay",
            feed_healthy=True,
            poll_interval_seconds=1,
        ),
        cache,
    )
    monkeypatch.setattr("core.nifty_ltp_feed.default_cache_path", lambda: cache)
    monkeypatch.setattr(
        "core.nifty_ltp_feed._resolved_cache_path",
        lambda path=None: path or cache,
    )
    provider: ReplayMarketProvider = ReplayMarketProvider()
    assert provider.mode is MarketDataMode.UAT_REPLAY
    assert provider.get_nifty_ltp(max_age_seconds=60) == pytest.approx(25123.45)


def test_uat_button_message_exact_phrase() -> None:
    text = uat_button_disabled_message("Live Price")
    assert "Feature unavailable in UAT mode" in text
    assert UAT_LOG_TAG in text


def test_live_tag_constant() -> None:
    assert LIVE_LOG_TAG == "[DRISHTI LIVE]"
