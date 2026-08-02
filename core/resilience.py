"""
Batman v3 — Resilience utilities.

Provides:
    • ``retry``  — Decorator with exponential backoff for transient failures.
    • ``CircuitBreaker`` — Stops calling a failing dependency after N errors,
                          auto-resets after a cooldown period.
    • ``confirm_order`` — Polls order status to verify TRADED.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import cast

from .exceptions import BrokerConnectionError, OrderPlacementError

logger = logging.getLogger("batman.resilience")


# ── Retry Decorator ──────────────────────────────────────────

_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    BrokerConnectionError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retryable: tuple[type[Exception], ...] | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
):
    """Decorator — retry a function on transient exceptions.

    Uses exponential backoff: delay = base_delay * backoff_factor^(attempt-1),
    capped at ``max_delay``.

    Args:
        max_attempts:   Total tries (including the first).
        base_delay:     Initial delay in seconds.
        max_delay:      Maximum delay between retries.
        backoff_factor: Multiplier applied each retry.
        retryable:      Exception types to retry on (default: transient broker errors).
        on_retry:       Optional callback(attempt, exception) called before each retry.

    Example::

        @retry(max_attempts=3, base_delay=1)
        def fetch_ltp():
            return broker.get_nifty_ltp()
    """
    retryable_types = retryable or _TRANSIENT_EXCEPTIONS

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_types as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            "[retry] %s failed after %d attempts: %s",
                            func.__name__,
                            max_attempts,
                            exc,
                        )
                        raise
                    delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
                    logger.warning(
                        "[retry] %s attempt %d/%d failed (%s) — retrying in %.1fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    if on_retry:
                        on_retry(attempt, exc)
                    time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


# ── Circuit Breaker ──────────────────────────────────────────


class CircuitState(Enum):
    CLOSED = auto()  # Normal — requests flow through
    OPEN = auto()  # Tripped — requests fail immediately
    HALF_OPEN = auto()  # Testing — one request allowed through


class CircuitBreaker:
    """Prevents cascading failures by tripping after ``failure_threshold``
    consecutive errors.  After ``recovery_timeout`` seconds the circuit
    enters HALF_OPEN and allows one test request.

    Usage::

        cb = CircuitBreaker("broker", failure_threshold=5, recovery_timeout=60)

        with cb:
            result = broker.get_nifty_ltp()

        # or as decorator:
        @cb.protect
        def get_ltp():
            return broker.get_nifty_ltp()
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: datetime | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if cooldown has elapsed
                if self._last_failure_time and datetime.now() - self._last_failure_time > timedelta(
                    seconds=self.recovery_timeout
                ):
                    self._state = CircuitState.HALF_OPEN
                    logger.info("[circuit:%s] OPEN → HALF_OPEN (cooldown elapsed)", self.name)
            return self._state

    def record_success(self) -> None:
        """Record a successful call — reset failure count."""
        with self._lock:
            self._failure_count = 0
            if self._state != CircuitState.CLOSED:
                logger.info("[circuit:%s] → CLOSED (success)", self.name)
                self._state = CircuitState.CLOSED

    def record_failure(self, exc: Exception | None = None) -> None:
        """Record a failed call — may trip the circuit."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()

            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.error(
                        "[circuit:%s] → OPEN after %d failures: %s",
                        self.name,
                        self._failure_count,
                        exc,
                    )
                self._state = CircuitState.OPEN

    def allow_request(self) -> bool:
        """True if the circuit allows a request through."""
        s = self.state  # triggers OPEN → HALF_OPEN check
        return s in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def __enter__(self):
        if not self.allow_request():
            raise BrokerConnectionError(
                f"Circuit breaker '{self.name}' is OPEN — broker unavailable"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure(exc_val)
        return False  # don't suppress exceptions

    def protect(self, func: Callable) -> Callable:
        """Decorator form of the circuit breaker."""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)

        return wrapper

    def status(self) -> dict:
        """Return a JSON-serializable status dict."""
        return {
            "name": self.name,
            "state": self.state.name,
            "failure_count": self._failure_count,
            "threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# ── Order Confirmation ───────────────────────────────────────


def confirm_order(
    broker,
    order_id: str,
    max_wait: float = 10.0,
    poll_interval: float = 1.0,
    expected_status: str = "TRADED",
) -> str:
    """Poll order status until it reaches ``expected_status`` or times out.

    Args:
        broker:          BatmanBroker instance.
        order_id:        Order ID to check.
        max_wait:        Maximum seconds to wait.
        poll_interval:   Seconds between polls.
        expected_status: Status to wait for.

    Returns:
        Final order status string.

    Raises:
        OrderPlacementError: If the order is REJECTED or times out.
    """
    start = time.time()
    last_status = "UNKNOWN"

    while time.time() - start < max_wait:
        try:
            last_status = cast(str, broker.get_order_status(order_id))
        except Exception as exc:
            logger.warning("[confirm] Status poll failed for %s: %s", order_id, exc)
            time.sleep(poll_interval)
            continue

        if last_status == expected_status:
            logger.info("[confirm] Order %s → %s ✓", order_id, expected_status)
            return last_status

        if last_status in ("REJECTED", "CANCELLED"):
            raise OrderPlacementError(
                f"Order {order_id} was {last_status} (expected {expected_status})"
            )

        time.sleep(poll_interval)

    logger.warning("[confirm] Order %s timed out — last status: %s", order_id, last_status)
    return last_status
