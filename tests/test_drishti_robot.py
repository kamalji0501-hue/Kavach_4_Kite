"""Tests for DRISHTI robot hardening helpers."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bat_telegram.bots.drishti.bot import should_send_type1_token_reminder
from bat_telegram.bots.drishti.nifty_feed_integration import (
    build_default_feed_config,
    ensure_default_feed_config,
    mark_ltp_cache_unhealthy,
)
from core.nifty_ltp_feed import read_nifty_ltp_cache
from core.token_store import TokenStore, jwt_expires_in_hours


def _fake_jwt(exp_hours_from_now: float) -> str:
    exp = int((datetime.now(UTC) + timedelta(hours=exp_hours_from_now)).timestamp())
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"hdr.{payload}.sig"


def test_should_send_type1_when_no_token() -> None:
    assert should_send_type1_token_reminder(
        has_token=False, expires_in_hours=None, warning_minutes=60
    )


def test_should_suppress_type1_when_token_valid() -> None:
    assert not should_send_type1_token_reminder(
        has_token=True, expires_in_hours=12.0, warning_minutes=60
    )


def test_should_send_type1_within_warning_window() -> None:
    assert should_send_type1_token_reminder(
        has_token=True, expires_in_hours=0.5, warning_minutes=60
    )


def test_ensure_default_feed_config_creates_file(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "feed.json"
    monkeypatch.setattr("core.nifty_ltp_feed._DEFAULT_CONFIG_PATH", cfg_path)
    cfg, created = ensure_default_feed_config(
        {"nifty_ltp_feed": {"default_poll_interval_seconds": 3}}
    )
    assert created is True
    assert cfg.poll_interval_seconds == 3
    cfg2, created2 = ensure_default_feed_config()
    assert created2 is False
    assert cfg2.poll_interval_seconds == 3


def test_build_default_feed_config_reads_params() -> None:
    cfg = build_default_feed_config(
        {"nifty_ltp_feed": {"rest_max_attempts": 4, "rate_limit_cooldown_seconds": 45}}
    )
    assert cfg.rest_max_attempts == 4
    assert cfg.rate_limit_cooldown_seconds == pytest.approx(45.0)


def test_mark_ltp_cache_unhealthy(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(
        "core.nifty_ltp_feed.default_cache_path", lambda: cache_path
    )
    monkeypatch.setattr("core.nifty_ltp_feed._DEFAULT_CACHE_PATH", cache_path)
    mark_ltp_cache_unhealthy(reason="test")
    snap = read_nifty_ltp_cache(cache_path)
    assert snap is not None
    assert snap.feed_healthy is False


def test_jwt_expires_in_hours() -> None:
    token = _fake_jwt(2.0)
    hours = jwt_expires_in_hours(token)
    assert hours is not None
    assert 1.5 < hours <= 2.1


def test_token_store_effective_expiry_uses_sooner(tmp_path: Path) -> None:
    store = TokenStore(path=tmp_path / "token.json")
    token = _fake_jwt(0.5)
    store.save(token)
    effective = store.effective_expires_in_hours()
    assert effective is not None
    assert effective <= 0.6


def test_write_nifty_ltp_cache_atomic(tmp_path: Path, monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from core.nifty_ltp_feed import (
        NiftyLtpCacheSnapshot,
        read_nifty_ltp_cache,
        write_nifty_ltp_cache,
    )

    cache_path = tmp_path / "nifty_ltp_cache.json"
    monkeypatch.setattr("core.nifty_ltp_feed._DEFAULT_CACHE_PATH", cache_path)
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    snap = NiftyLtpCacheSnapshot(
        ltp=23500.5,
        updated_at=now.isoformat(),
        last_changed_at=now.isoformat(),
        source="test",
        feed_healthy=True,
        poll_interval_seconds=2,
    )
    write_nifty_ltp_cache(snap, cache_path)
    loaded = read_nifty_ltp_cache(cache_path)
    assert loaded is not None
    assert loaded.ltp == pytest.approx(23500.5)
