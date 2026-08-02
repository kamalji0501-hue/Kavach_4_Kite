"""Shared Telegram send retry helpers for alerting paths."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

logger = logging.getLogger("batman.telegram_delivery")


async def send_with_retry(
    send_callable: Callable[..., Any],
    /,
    *args,
    max_attempts: int = 4,
    base_delay_seconds: float = 2.0,
    max_delay_seconds: float = 30.0,
    log_prefix: str = "Telegram send",
    **kwargs,
) -> bool:
    """Retry transient Telegram send failures with bounded backoff."""
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            await send_callable(*args, **kwargs)
            if attempt > 1:
                logger.info("%s succeeded on retry %s/%s", log_prefix, attempt, max_attempts)
            return True
        except Exception as exc:
            last_exc = exc
            retry_after = getattr(exc, "retry_after", None)
            is_rate_limited = retry_after is not None
            is_transient = exc.__class__.__name__ in {"TimedOut", "NetworkError"}
            if not is_rate_limited and not is_transient:
                break
            if attempt >= max_attempts:
                break
            if is_rate_limited:
                retry_after_value = retry_after
                if isinstance(retry_after_value, timedelta):
                    retry_after_value = retry_after_value.total_seconds()
                delay = min(
                    max(float(retry_after_value or 0) + 1.0, base_delay_seconds),
                    max_delay_seconds,
                )
                logger.warning(
                    "%s rate limited on attempt %s/%s — retrying in %.1fs",
                    log_prefix,
                    attempt,
                    max_attempts,
                    delay,
                )
            else:
                delay = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
                logger.warning(
                    "%s transient failure on attempt %s/%s (%s) — retrying in %.1fs",
                    log_prefix,
                    attempt,
                    max_attempts,
                    exc,
                    delay,
                )
            await asyncio.sleep(delay)
    logger.warning("%s failed after %s attempts: %s", log_prefix, max_attempts, last_exc)
    return False
