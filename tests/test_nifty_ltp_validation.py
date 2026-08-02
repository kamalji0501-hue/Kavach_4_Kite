"""Tests for NIFTY LTP cache validation on DRISHTI user pings."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core.nifty_ltp_feed import (
    DEFAULT_USER_PING_CRITICAL_AGE_SECONDS,
    DEFAULT_USER_PING_WARNING_AGE_SECONDS,
    NiftyLtpCacheSnapshot,
    NiftyLtpFeedConfig,
    allowed_user_ping_critical_options,
    allowed_user_ping_warning_options,
)
from core.nifty_ltp_validation import (
    assess_cache_for_user_ping,
    resolve_user_ping_thresholds,
    user_ping_display_max_age,
)

_IST = ZoneInfo("Asia/Kolkata")


def _snap(*, age_seconds: float, ltp: float = 23500.0, healthy: bool = True) -> NiftyLtpCacheSnapshot:
    now = datetime.now(_IST)
    updated = now - timedelta(seconds=age_seconds)
    return NiftyLtpCacheSnapshot(
        ltp=ltp,
        updated_at=updated.isoformat(),
        last_changed_at=updated.isoformat(),
        feed_healthy=healthy,
        poll_interval_seconds=2,
    )


def _cfg(**kwargs) -> NiftyLtpFeedConfig:
    defaults = dict(
        poll_interval_seconds=2,
        stale_price_alert_seconds=10,
        user_ping_warning_age_seconds=15,
        user_ping_critical_age_seconds=60,
    )
    defaults.update(kwargs)
    return NiftyLtpFeedConfig(**defaults)


def test_fresh_cache_acceptable_in_session() -> None:
    snap = _snap(age_seconds=3.0)
    result = assess_cache_for_user_ping(snap, _cfg(), in_market_session=True)
    assert result.acceptable_for_display is True
    assert result.requires_live_fetch is False
    assert result.severity == "ok"


def test_warning_when_cache_older_than_configured_limit() -> None:
    cfg = _cfg(user_ping_warning_age_seconds=15)
    snap = _snap(age_seconds=20.0, ltp=23497.15)
    result = assess_cache_for_user_ping(snap, cfg, in_market_session=True)
    assert result.severity == "warning"
    assert "limit 15s" in result.warning_message


def test_critical_when_cache_older_than_configured_critical() -> None:
    cfg = _cfg(user_ping_critical_age_seconds=60)
    snap = _snap(age_seconds=70.0, ltp=23497.15)
    result = assess_cache_for_user_ping(snap, cfg, in_market_session=True)
    assert result.severity == "critical"
    assert result.should_report_incident is True


def test_invalid_timestamp_is_critical() -> None:
    snap = NiftyLtpCacheSnapshot(
        ltp=23500.0,
        updated_at="not-a-timestamp",
        last_changed_at="not-a-timestamp",
        feed_healthy=True,
    )
    result = assess_cache_for_user_ping(snap, _cfg(), in_market_session=True)
    assert result.severity == "critical"
    assert result.should_report_incident is True


def test_off_hours_never_displays_cache() -> None:
    snap = _snap(age_seconds=5.0)
    result = assess_cache_for_user_ping(snap, _cfg(), in_market_session=False)
    assert result.acceptable_for_display is False
    assert result.requires_live_fetch is True


def test_off_hours_yesterday_cache_is_critical() -> None:
    snap = _snap(age_seconds=3600 * 12, ltp=23497.15)
    result = assess_cache_for_user_ping(snap, _cfg(), in_market_session=False)
    assert result.severity == "critical"


def test_config_allows_warning_below_feed_freshness_floor() -> None:
    """Stored ping warning may be below feed floor; effective_* raises it at runtime."""
    cfg = NiftyLtpFeedConfig(
        poll_interval_seconds=2,
        stale_price_alert_seconds=5,
        rest_stale_critical_seconds=15,
        user_ping_warning_age_seconds=5,
        user_ping_critical_age_seconds=5,
    )
    assert cfg.user_ping_warning_age_seconds == 5
    assert cfg.effective_user_ping_warning_age_seconds() >= 15


def test_allowed_warning_options_respect_poll_interval() -> None:
    assert allowed_user_ping_warning_options(2) == (10, 15, 20, 30, 45, 60)
    assert allowed_user_ping_warning_options(5) == (15, 20, 30, 45, 60)


def test_allowed_critical_options_respect_warning_floor() -> None:
    assert 15 in allowed_user_ping_critical_options(15)
    assert 30 in allowed_user_ping_critical_options(15)
    assert 30 in allowed_user_ping_critical_options(30)
    assert 20 not in allowed_user_ping_critical_options(30)

def test_resolve_thresholds_defaults_without_config() -> None:
    t = resolve_user_ping_thresholds(None)
    assert t.warning_seconds == float(DEFAULT_USER_PING_WARNING_AGE_SECONDS)
    assert t.critical_seconds == float(DEFAULT_USER_PING_CRITICAL_AGE_SECONDS)


def test_user_ping_display_max_age_uses_configured_warning() -> None:
    cfg = _cfg(user_ping_warning_age_seconds=20)
    assert user_ping_display_max_age(cfg) == 20.0
