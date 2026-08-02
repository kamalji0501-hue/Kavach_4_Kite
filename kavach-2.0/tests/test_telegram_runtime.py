from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.telegram_delivery import send_with_retry
from core.telegram_runtime import (
    PollingRestartPolicy,
    cleanup_managed_runtime,
    create_managed_task,
    register_shutdown_callback,
)


def test_polling_restart_policy_network_backoff_grows() -> None:
    class NetworkError(Exception):
        pass

    policy = PollingRestartPolicy(base_delay_seconds=5.0, max_delay_seconds=90.0)
    first = policy.delay_for_exception(NetworkError("down"), failure_streak=1)
    third = policy.delay_for_exception(NetworkError("down"), failure_streak=3)
    assert first == pytest.approx(5.0)
    assert third > first


def test_polling_restart_policy_retry_after_respects_server_delay() -> None:
    class RetryAfter(Exception):
        def __init__(self, retry_after: float) -> None:
            super().__init__("retry later")
            self.retry_after = retry_after

    policy = PollingRestartPolicy(base_delay_seconds=5.0, max_delay_seconds=90.0)
    delay = policy.delay_for_exception(RetryAfter(17), failure_streak=1)
    assert delay == pytest.approx(18.0)


@pytest.mark.asyncio
async def test_send_with_retry_recovers_after_timeout() -> None:
    class TimedOut(Exception):
        pass

    calls: list[int] = []

    async def flaky_send(*args, **kwargs) -> None:
        del args, kwargs
        calls.append(1)
        if len(calls) < 3:
            raise TimedOut("slow")

    ok = await send_with_retry(
        flaky_send,
        max_attempts=4,
        base_delay_seconds=0.01,
        max_delay_seconds=0.02,
        log_prefix="test send",
    )
    assert ok is True
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_send_with_retry_returns_false_after_exhaustion() -> None:
    class NetworkError(Exception):
        pass

    async def failing_send(*args, **kwargs) -> None:
        del args, kwargs
        raise NetworkError("offline")

    ok = await send_with_retry(
        failing_send,
        max_attempts=2,
        base_delay_seconds=0.01,
        max_delay_seconds=0.02,
        log_prefix="test send",
    )
    assert ok is False


@pytest.mark.asyncio
async def test_cleanup_managed_runtime_cancels_tasks_and_runs_callbacks() -> None:
    app = SimpleNamespace(bot_data={})
    events: list[str] = []

    async def forever() -> None:
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            events.append("task_cancelled")
            raise

    async def async_shutdown() -> None:
        events.append("async_shutdown")

    def sync_shutdown() -> None:
        events.append("sync_shutdown")

    create_managed_task(app, "forever", forever(), name="forever")
    register_shutdown_callback(app, sync_shutdown)
    register_shutdown_callback(app, async_shutdown)
    await asyncio.sleep(0)

    await cleanup_managed_runtime(app)

    assert "sync_shutdown" in events
    assert "async_shutdown" in events
    assert "task_cancelled" in events
