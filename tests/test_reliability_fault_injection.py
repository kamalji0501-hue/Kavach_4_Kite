"""Controlled fault-injection tests (mocked / local — no live NIFTY required)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.nifty_ltp_feed import NiftyLtpCacheSnapshot, write_nifty_ltp_cache
from core.startup_gates import ltp_gate_skip_reason, wait_drishti_ltp_ready
from core.telegram_delivery import send_with_retry
from core.telegram_runtime import (
    PollingRestartPolicy,
    cleanup_managed_runtime,
    create_managed_task,
)


def test_ltp_gate_skipped_post_market() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    after_close = datetime(2026, 6, 25, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert ltp_gate_skip_reason(now=after_close) == "post_market"


@pytest.mark.asyncio
async def test_telegram_fault_injection_rate_limit_then_success() -> None:
    class RetryAfter(Exception):
        def __init__(self, retry_after: float) -> None:
            super().__init__("flood")
            self.retry_after = retry_after

    calls = 0

    async def flaky(*_a, **_k) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryAfter(0.01)

    ok = await send_with_retry(
        flaky,
        max_attempts=3,
        base_delay_seconds=0.01,
        max_delay_seconds=0.05,
        log_prefix="fault inject",
    )
    assert ok is True
    assert calls == 2


def test_cache_write_contention_fault_injection(tmp_path: Path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cache = tmp_path / "nifty_ltp_cache.json"
    now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    snap = NiftyLtpCacheSnapshot(ltp=24000.0, updated_at=now, last_changed_at=now)
    real_replace = os.replace

    def always_locked(_src: str, _dst: str) -> None:
        err = PermissionError("Access is denied")
        err.winerror = 5
        raise err

    with patch("core.nifty_ltp_feed.os.replace", always_locked):
        result = write_nifty_ltp_cache(snap, cache)
    assert result is False


def test_polling_restart_policy_crash_backoff_fault_injection() -> None:
    policy = PollingRestartPolicy(base_delay_seconds=5.0, max_delay_seconds=90.0)
    d1 = policy.delay_for_exception(RuntimeError("boom"), failure_streak=1)
    d3 = policy.delay_for_exception(RuntimeError("boom"), failure_streak=3)
    assert d3 > d1


@pytest.mark.asyncio
async def test_managed_task_duplicate_start_fault_injection() -> None:
    """Second create_managed_task with same key cancels the first."""
    app = SimpleNamespace(bot_data={})
    cancelled: list[str] = []

    async def worker(name: str) -> None:
        try:
            while True:
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    create_managed_task(app, "feed", worker("a"), name="feed")
    await asyncio.sleep(0)
    create_managed_task(app, "feed", worker("b"), name="feed")
    await asyncio.sleep(0)
    await cleanup_managed_runtime(app)
    assert "a" in cancelled


def test_wait_drishti_ltp_ready_skips_off_hours(tmp_path: Path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    with patch("core.startup_gates.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 25, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        mock_dt.fromisoformat = datetime.fromisoformat
        ok, detail = wait_drishti_ltp_ready(root=tmp_path, timeout_seconds=1.0)
    assert ok is True
    assert "post_market" in detail


def test_token_refresh_transition_fault_injection(tmp_path: Path) -> None:
    """Simulate DRISHTI saving JWT → KAVACH bootstrap callback fires once."""
    import time

    from core.token_store import TokenStore
    from core.token_watch import start_token_watch

    token_path = tmp_path / "access_token.json"
    TokenStore(path=token_path).save("refresh.jwt.token")
    bootstrapped: list[str] = []

    def on_ready(token: str) -> None:
        bootstrapped.append(token)

    stop = start_token_watch(
        None,
        client_code="1106926362",
        token_path=token_path,
        poll_seconds=0.05,
        on_token_ready=on_ready,
    )
    time.sleep(0.3)
    stop.set()
    assert bootstrapped == ["refresh.jwt.token"]
