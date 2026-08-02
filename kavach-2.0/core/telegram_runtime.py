"""Shared PTB runtime helpers for restart policy and managed tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from telegram.ext import Application

logger = logging.getLogger("batman.telegram_runtime")

_TASKS_KEY = "_managed_async_tasks"
_SHUTDOWN_CALLBACKS_KEY = "_managed_shutdown_callbacks"


def _task_store(app: Application) -> dict[str, asyncio.Task[Any]]:
    store = app.bot_data.get(_TASKS_KEY)
    if not isinstance(store, dict):
        store = {}
        app.bot_data[_TASKS_KEY] = store
    return store


def _shutdown_store(app: Application) -> list[Callable[[], Any]]:
    store = app.bot_data.get(_SHUTDOWN_CALLBACKS_KEY)
    if not isinstance(store, list):
        store = []
        app.bot_data[_SHUTDOWN_CALLBACKS_KEY] = store
    return store


def create_managed_task(
    app: Application,
    key: str,
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
) -> asyncio.Task[Any]:
    """Create one managed background task per key, canceling the previous one."""
    store = _task_store(app)
    existing = store.get(key)
    if existing is not None and not existing.done():
        existing.cancel()
    task = asyncio.create_task(cast(Any, coro), name=name or key)
    store[key] = task
    return task


def register_shutdown_callback(app: Application, callback: Callable[[], Any]) -> None:
    """Register a sync or async callback invoked during app runtime cleanup."""
    _shutdown_store(app).append(callback)


async def cleanup_managed_runtime(app: Application) -> None:
    """Cancel registered tasks and invoke registered shutdown callbacks once."""
    callbacks = list(_shutdown_store(app))
    app.bot_data[_SHUTDOWN_CALLBACKS_KEY] = []
    for callback in callbacks:
        try:
            result = callback()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning("Runtime shutdown callback failed: %s", exc)

    tasks = list(_task_store(app).values())
    app.bot_data[_TASKS_KEY] = {}
    for task in tasks:
        if not task.done():
            task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Managed runtime task failed during cleanup: %s", exc)


@dataclass
class PollingRestartPolicy:
    """Compute bounded restart delays for polling-loop failures."""

    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 90.0
    network_backoff_factor: float = 2.0
    crash_backoff_factor: float = 2.5

    def delay_for_exception(self, exc: BaseException | None, *, failure_streak: int) -> float:
        if exc is not None and hasattr(exc, "retry_after"):
            retry_after = getattr(exc, "retry_after", 0) or 0
            if isinstance(retry_after, timedelta):
                retry_after = retry_after.total_seconds()
            return min(max(float(retry_after) + 1.0, self.base_delay_seconds), self.max_delay_seconds)
        if exc is not None and exc.__class__.__name__ in {"TimedOut", "NetworkError"}:
            return min(
                self.base_delay_seconds * (self.network_backoff_factor ** max(0, failure_streak - 1)),
                self.max_delay_seconds,
            )
        return min(
            self.base_delay_seconds * (self.crash_backoff_factor ** max(0, failure_streak - 1)),
            self.max_delay_seconds,
        )
