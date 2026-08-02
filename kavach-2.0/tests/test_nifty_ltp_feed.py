"""Tests for core.nifty_ltp_feed."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from core.exceptions import BrokerConnectionError
from core.nifty_ltp_audit import append_rest_ltp_log
from core.nifty_ltp_feed import (
    DEFAULT_REST_STALE_CRITICAL_SECONDS,
    DEFAULT_WEBSOCKET_STALE_CRITICAL_SECONDS,
    FEED_MODE_REST,
    FEED_MODE_WEBSOCKET,
    NiftyLtpCacheSnapshot,
    NiftyLtpFeedConfig,
    _FeedRuntime,
    append_nifty_ltp_audit_log,
    compute_unchanged_seconds,
    is_within_feed_startup_grace,
    is_within_transport_grace,
    load_feed_config,
    mark_transport_started,
    read_nifty_ltp_cache,
    resolve_nifty_ltp_from_cache,
    run_feed_stale_watchdog,
    save_feed_config,
    seed_nifty_ltp_cache,
    should_alert_stale_price,
    write_nifty_ltp_cache,
)

_IST = ZoneInfo("Asia/Kolkata")


def test_feed_config_roundtrip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "feed.json"
    cfg = NiftyLtpFeedConfig(
        poll_interval_seconds=2,
        stale_price_alert_seconds=10,
        rest_max_attempts=4,
        rate_limit_cooldown_seconds=45.0,
    )
    save_feed_config(cfg, cfg_path)
    loaded = load_feed_config(cfg_path)
    assert loaded is not None
    assert loaded.poll_interval_seconds == 2
    assert loaded.stale_price_alert_seconds == 10
    assert loaded.rest_max_attempts == 4
    assert loaded.rate_limit_cooldown_seconds == pytest.approx(45.0)


def test_feed_config_loads_retry_defaults(tmp_path: Path) -> None:
    cfg_path = tmp_path / "feed.json"
    cfg_path.write_text(
        '{"poll_interval_seconds": 3, "stale_price_alert_seconds": 15}', encoding="utf-8"
    )
    loaded = load_feed_config(cfg_path)
    assert loaded is not None
    assert loaded.rest_max_attempts == 3
    assert loaded.rate_limit_cooldown_seconds == pytest.approx(30.0)
    assert loaded.user_ping_warning_age_seconds == 15
    assert loaded.user_ping_critical_age_seconds == 60


def test_feed_config_ping_threshold_roundtrip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "feed.json"
    cfg = NiftyLtpFeedConfig(
        poll_interval_seconds=2,
        stale_price_alert_seconds=10,
        user_ping_warning_age_seconds=15,
        user_ping_critical_age_seconds=60,
    )
    save_feed_config(cfg, cfg_path)
    loaded = load_feed_config(cfg_path)
    assert loaded is not None
    assert loaded.user_ping_warning_age_seconds == 15
    assert loaded.user_ping_critical_age_seconds == 60


def test_allowed_user_ping_warning_options_poll_five() -> None:
    from core.nifty_ltp_feed import allowed_user_ping_warning_options

    assert allowed_user_ping_warning_options(5) == (15, 20, 30, 45, 60)


def test_feed_config_invalid_poll_raises() -> None:
    with pytest.raises(ValueError):
        NiftyLtpFeedConfig(poll_interval_seconds=7)


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    now = datetime.now(_IST).isoformat()
    snap = NiftyLtpCacheSnapshot(
        ltp=24856.75,
        updated_at=now,
        last_changed_at=now,
    )
    write_nifty_ltp_cache(snap, cache_path)
    loaded = read_nifty_ltp_cache(cache_path)
    assert loaded is not None
    assert loaded.ltp == pytest.approx(24856.75)
    assert loaded.is_fresh(max_age_seconds=5.0)


def test_write_nifty_ltp_cache_retries_windows_replace_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    now = datetime.now(_IST).isoformat()
    snap = NiftyLtpCacheSnapshot(
        ltp=24856.75,
        updated_at=now,
        last_changed_at=now,
    )
    real_replace = __import__("os").replace
    attempts = {"count": 0}

    def flaky_replace(src: str, dst: str) -> None:
        attempts["count"] += 1
        if attempts["count"] < 4:
            err = PermissionError("Access is denied")
            err.winerror = 5
            raise err
        real_replace(src, dst)

    monkeypatch.setattr("core.nifty_ltp_feed.os.replace", flaky_replace)
    assert write_nifty_ltp_cache(snap, cache_path) is True
    loaded = read_nifty_ltp_cache(cache_path)
    assert loaded is not None
    assert loaded.ltp == pytest.approx(24856.75)
    assert attempts["count"] == 4


def test_write_nifty_ltp_cache_returns_false_on_persistent_replace_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    now = datetime.now(_IST).isoformat()
    snap = NiftyLtpCacheSnapshot(
        ltp=24856.75,
        updated_at=now,
        last_changed_at=now,
    )

    def always_locked_replace(src: str, dst: str) -> None:
        err = PermissionError("Access is denied")
        err.winerror = 5
        raise err

    monkeypatch.setattr("core.nifty_ltp_feed.os.replace", always_locked_replace)
    assert write_nifty_ltp_cache(snap, cache_path) is False
    assert read_nifty_ltp_cache(cache_path) is None


def test_compute_unchanged_seconds_resets_on_price_change() -> None:
    now = datetime.now(_IST)
    prev = now - timedelta(seconds=12)
    unchanged, changed_at = compute_unchanged_seconds(
        previous_ltp=24800.0,
        new_ltp=24801.0,
        last_changed_at=prev,
        now=now,
    )
    assert unchanged == 0.0
    assert changed_at == now


def test_compute_unchanged_seconds_accumulates() -> None:
    now = datetime.now(_IST)
    prev = now - timedelta(seconds=12)
    unchanged, changed_at = compute_unchanged_seconds(
        previous_ltp=24800.0,
        new_ltp=24800.0,
        last_changed_at=prev,
        now=now,
    )
    assert unchanged == pytest.approx(12.0)
    assert changed_at == prev


def test_should_alert_stale_price_only_in_session() -> None:
    assert should_alert_stale_price(10.0, 10, in_market_session=True) is True
    assert should_alert_stale_price(9.0, 10, in_market_session=True) is False
    assert should_alert_stale_price(30.0, 10, in_market_session=False) is False


def test_load_feed_config_missing_returns_none(tmp_path: Path) -> None:
    assert load_feed_config(tmp_path / "missing.json") is None


@pytest.mark.asyncio
@patch("core.nifty_ltp_feed.fetch_nifty_ltp_rest_with_retry")
async def test_feed_rate_limit_does_not_increment_failures(mock_fetch, tmp_path: Path) -> None:
    from core.exceptions import BrokerConnectionError
    from core.nifty_ltp_feed import NiftyLtpFeedService

    mock_fetch.side_effect = BrokerConnectionError("Too many requests (HTTP 429)")

    service = NiftyLtpFeedService(
        client_code="1106926362",
        token_getter=lambda: "jwt",
        config=NiftyLtpFeedConfig(
            poll_interval_seconds=2,
            stale_price_alert_seconds=10,
            rate_limit_cooldown_seconds=30.0,
        ),
        cache_path=tmp_path / "cache.json",
        log_dir=tmp_path / "logs",
        trading_day_check=lambda _d: True,
    )
    service._runtime.last_ltp = 23500.0
    service._runtime.last_changed_at = datetime.now(_IST)

    with patch(
        "core.nifty_ltp_feed.is_nse_market_session",
        return_value=True,
    ):
        await service._tick()

    assert service._runtime.consecutive_failures == 0
    assert service._runtime.rate_limit_until is not None
    snap = read_nifty_ltp_cache(tmp_path / "cache.json")
    assert snap is not None
    assert snap.feed_healthy is True
    assert snap.ltp == pytest.approx(23500.0)


def test_feed_config_websocket_mode_consumer_age() -> None:
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET)
    assert cfg.consumer_max_age_seconds() == float(DEFAULT_WEBSOCKET_STALE_CRITICAL_SECONDS)
    assert cfg.is_websocket_mode()


def test_feed_config_rest_consumer_age() -> None:
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_REST, poll_interval_seconds=2)
    assert cfg.consumer_max_age_seconds() == float(DEFAULT_REST_STALE_CRITICAL_SECONDS)


def test_same_price_fresh_if_updated_at_recent(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    now = datetime.now(_IST).isoformat()
    write_nifty_ltp_cache(
        NiftyLtpCacheSnapshot(
            ltp=25231.5,
            updated_at=now,
            last_changed_at=(datetime.now(_IST) - timedelta(seconds=120)).isoformat(),
            source="dhan_websocket",
            feed_healthy=True,
        ),
        cache_path,
    )
    with patch(
        "core.nifty_ltp_feed.load_feed_config",
        return_value=NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET),
    ):
        ltp = resolve_nifty_ltp_from_cache(path=cache_path)
    assert ltp == pytest.approx(25231.5)


def test_append_rest_ltp_log_in_rest_folder(tmp_path: Path) -> None:
    now = datetime(2026, 6, 7, 9, 15, 1, tzinfo=_IST)
    path = append_rest_ltp_log(tmp_path, now, 23382.6)
    assert path.name == "rest_ltp_20260607.log"
    assert "23382.60" in path.read_text(encoding="utf-8")


def test_feed_config_stale_thresholds_roundtrip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "feed.json"
    cfg = NiftyLtpFeedConfig(
        feed_mode=FEED_MODE_WEBSOCKET,
        websocket_stale_critical_seconds=5,
        rest_stale_critical_seconds=10,
    )
    save_feed_config(cfg, cfg_path)
    loaded = load_feed_config(cfg_path)
    assert loaded is not None
    assert loaded.websocket_stale_critical_seconds == 5
    assert loaded.rest_stale_critical_seconds == 10


def test_legacy_external_websocket_migrates_to_websocket(tmp_path: Path) -> None:
    cfg_path = tmp_path / "feed.json"
    cfg_path.write_text(
        '{"feed_mode": "external_websocket", "poll_interval_seconds": 2}',
        encoding="utf-8",
    )
    loaded = load_feed_config(cfg_path)
    assert loaded is not None
    assert loaded.feed_mode == FEED_MODE_WEBSOCKET


def test_feed_config_invalid_mode_raises() -> None:
    with pytest.raises(ValueError):
        NiftyLtpFeedConfig(feed_mode="invalid")


def test_resolve_nifty_ltp_from_cache_ok(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    now = datetime.now(_IST).isoformat()
    write_nifty_ltp_cache(
        NiftyLtpCacheSnapshot(ltp=23500.0, updated_at=now, last_changed_at=now),
        cache_path,
    )
    with patch("core.nifty_ltp_feed.load_feed_config", return_value=None):
        ltp = resolve_nifty_ltp_from_cache(max_age_seconds=30.0, path=cache_path)
    assert ltp == pytest.approx(23500.0)


def test_resolve_nifty_ltp_from_cache_stale_raises(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    old = (datetime.now(_IST) - timedelta(seconds=60)).isoformat()
    write_nifty_ltp_cache(
        NiftyLtpCacheSnapshot(ltp=23500.0, updated_at=old, last_changed_at=old),
        cache_path,
    )
    with pytest.raises(BrokerConnectionError, match="stale or missing"):
        resolve_nifty_ltp_from_cache(max_age_seconds=5.0, path=cache_path)


def test_seed_nifty_ltp_cache_writes_fresh_snapshot(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    snap = seed_nifty_ltp_cache(23382.6, path=cache_path)
    assert snap.ltp == pytest.approx(23382.6)
    assert snap.feed_healthy is True
    loaded = read_nifty_ltp_cache(cache_path)
    assert loaded is not None
    assert loaded.is_fresh(max_age_seconds=30.0)


def test_append_nifty_ltp_audit_log_format(tmp_path: Path) -> None:
    now = datetime(2026, 6, 2, 10, 15, 1, tzinfo=_IST)
    path = append_nifty_ltp_audit_log(
        tmp_path,
        now,
        23382.6,
        "dhan_rest",
        event="poll",
    )
    assert path.name == "nifty_ltp_20260602.log"
    line = path.read_text(encoding="utf-8").strip()
    assert line == "2026-06-02 10:15:01 IST,23382.60,dhan_rest,poll"


def test_startup_grace_within_30s_after_open() -> None:
    open_time = datetime(2026, 6, 2, 9, 15, 10, tzinfo=_IST)
    with patch("core.nifty_ltp_feed.is_nse_market_session", return_value=True):
        assert is_within_feed_startup_grace(open_time, grace_seconds=30) is True
    later = datetime(2026, 6, 2, 9, 15, 45, tzinfo=_IST)
    with patch("core.nifty_ltp_feed.is_nse_market_session", return_value=True):
        assert is_within_feed_startup_grace(later, grace_seconds=30) is False


@pytest.mark.asyncio
async def test_feed_stale_watchdog_ws_grace_suppresses_no_tick_alert() -> None:
    runtime = _FeedRuntime()
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET, websocket_startup_grace_seconds=30)
    events: list[str] = []

    class Hooks:
        async def on_fetch_failure(self, *, failures: int, threshold: int, error: str) -> None:
            return None

        async def on_auth_failure(self, *, error: str) -> None:
            return None

        async def on_fetch_recovered(self) -> None:
            return None

        async def on_feed_stale(self, *, age_seconds: float, threshold: float, error: str) -> None:
            events.append("stale")

        async def on_feed_stale_cleared(self) -> None:
            events.append("cleared")

        async def on_stale_price(
            self, *, ltp: float, unchanged_seconds: float, threshold: int
        ) -> None:
            return None

        async def on_stale_price_cleared(self, *, ltp: float) -> None:
            return None

    running = {"v": True}
    grace_now = datetime(2026, 6, 2, 9, 15, 5, tzinfo=_IST)

    async def _run_watchdog() -> None:
        with (
            patch("core.nifty_ltp_feed.is_nse_market_session", return_value=True),
            patch("core.nifty_ltp_feed.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = grace_now
            await run_feed_stale_watchdog(
                config=cfg,
                runtime=runtime,
                hooks=Hooks(),
                is_running=lambda: running["v"],
                trading_day_check=lambda _d: True,
                check_interval_seconds=0.05,
            )

    task = asyncio.create_task(_run_watchdog())
    await asyncio.sleep(0.2)
    running["v"] = False
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert "stale" not in events


@pytest.mark.asyncio
async def test_feed_stale_watchdog_ws_transport_grace_after_reconnect() -> None:
    runtime = _FeedRuntime()
    mark_transport_started(
        runtime,
        when=datetime(2026, 6, 2, 10, 46, 2, tzinfo=_IST),
    )
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_WEBSOCKET, websocket_startup_grace_seconds=30)
    events: list[str] = []

    class Hooks:
        async def on_fetch_failure(self, *, failures: int, threshold: int, error: str) -> None:
            return None

        async def on_auth_failure(self, *, error: str) -> None:
            return None

        async def on_fetch_recovered(self) -> None:
            return None

        async def on_feed_stale(self, *, age_seconds: float, threshold: float, error: str) -> None:
            events.append("stale")

        async def on_feed_stale_cleared(self) -> None:
            events.append("cleared")

        async def on_stale_price(
            self, *, ltp: float, unchanged_seconds: float, threshold: int
        ) -> None:
            return None

        async def on_stale_price_cleared(self, *, ltp: float) -> None:
            return None

    running = {"v": True}
    mid_grace = datetime(2026, 6, 2, 10, 46, 5, tzinfo=_IST)

    async def _run_watchdog() -> None:
        with (
            patch("core.nifty_ltp_feed.is_nse_market_session", return_value=True),
            patch("core.nifty_ltp_feed.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = mid_grace
            await run_feed_stale_watchdog(
                config=cfg,
                runtime=runtime,
                hooks=Hooks(),
                is_running=lambda: running["v"],
                trading_day_check=lambda _d: True,
                check_interval_seconds=0.05,
            )

    task = asyncio.create_task(_run_watchdog())
    await asyncio.sleep(0.2)
    running["v"] = False
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert "stale" not in events
    assert is_within_transport_grace(runtime, grace_seconds=30, now=mid_grace)


@pytest.mark.asyncio
async def test_feed_stale_watchdog_fires_on_no_refresh(tmp_path: Path) -> None:
    runtime = _FeedRuntime(
        last_update_at=datetime.now(_IST) - timedelta(seconds=12),
        last_ltp=25200.0,
    )
    cfg = NiftyLtpFeedConfig(feed_mode=FEED_MODE_REST)
    events: list[str] = []

    class Hooks:
        async def on_fetch_failure(self, *, failures: int, threshold: int, error: str) -> None:
            return None

        async def on_auth_failure(self, *, error: str) -> None:
            return None

        async def on_fetch_recovered(self) -> None:
            return None

        async def on_feed_stale(self, *, age_seconds: float, threshold: float, error: str) -> None:
            events.append("stale")

        async def on_feed_stale_cleared(self) -> None:
            events.append("cleared")

        async def on_stale_price(
            self, *, ltp: float, unchanged_seconds: float, threshold: int
        ) -> None:
            return None

        async def on_stale_price_cleared(self, *, ltp: float) -> None:
            return None

    running = {"v": True}

    async def _run_watchdog() -> None:
        with patch("core.nifty_ltp_feed.is_nse_market_session", return_value=True):
            await run_feed_stale_watchdog(
                config=cfg,
                runtime=runtime,
                hooks=Hooks(),
                is_running=lambda: running["v"],
                trading_day_check=lambda _d: True,
                check_interval_seconds=0.05,
            )

    task = asyncio.create_task(_run_watchdog())
    await asyncio.sleep(0.2)
    running["v"] = False
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert "stale" in events


def test_extract_ltp_from_ws_tick_skips_previous_close() -> None:
    from core.dhan_ws_tick import extract_ltp_from_ws_tick, is_dhan_ws_control_tick

    tick = {"type": "Previous Close", "close": 24500.0}
    assert is_dhan_ws_control_tick(tick) is True
    assert extract_ltp_from_ws_tick(tick) is None
    assert extract_ltp_from_ws_tick({"LTP": 24512.5}) == 24512.5
    assert extract_ltp_from_ws_tick({"LTP": 0}) is None
    assert extract_ltp_from_ws_tick("not-a-dict") is None


@pytest.mark.asyncio
async def test_websocket_feed_rate_limit_does_not_increment_failures(
    tmp_path: Path,
) -> None:
    from unittest.mock import MagicMock, patch

    from core.nifty_ltp_websocket_feed import NiftyLtpWebSocketFeedService

    service = NiftyLtpWebSocketFeedService(
        client_code="1106926362",
        token_getter=lambda: "jwt",
        config=NiftyLtpFeedConfig(
            feed_mode=FEED_MODE_WEBSOCKET,
            poll_interval_seconds=2,
            rate_limit_cooldown_seconds=0.05,
        ),
        cache_path=tmp_path / "cache.json",
        log_dir=tmp_path / "logs",
        trading_day_check=lambda _d: True,
        reconnect_base_seconds=0.01,
    )
    service._running = True
    connect_calls = {"n": 0}

    class FakeFeed:
        async def connect(self) -> None:
            connect_calls["n"] += 1
            if connect_calls["n"] == 1:
                raise RuntimeError("server rejected WebSocket connection: HTTP 429")
            service._running = False

        async def get_instrument_data(self):
            return {"LTP": 23500.0}

        async def disconnect(self) -> None:
            pass

    with (
        patch(
            "core.nifty_ltp_websocket_feed.is_nse_market_session",
            return_value=True,
        ),
        patch(
            "dhanhq.marketfeed.MarketFeed",
            return_value=FakeFeed(),
        ),
        patch(
            "dhanhq.DhanContext",
            return_value=MagicMock(),
        ),
    ):
        task = asyncio.create_task(service._collector_loop())
        await asyncio.wait_for(task, timeout=2.0)

    assert service._runtime.consecutive_failures == 0
    assert service._runtime.rate_limit_until is not None
