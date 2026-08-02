"""Tests for core.resilience — retry, circuit breaker, order confirmation."""

import time
from unittest.mock import MagicMock

import pytest

from core.exceptions import BrokerConnectionError, OrderPlacementError
from core.resilience import CircuitBreaker, CircuitState, confirm_order, retry


class TestRetry:

    def test_succeeds_on_first_try(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def always_works():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert always_works() == "ok"
        assert call_count == 1

    def test_retries_on_transient_error(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def fails_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise BrokerConnectionError("connection lost")
            return "recovered"

        assert fails_twice() == "recovered"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        @retry(max_attempts=2, base_delay=0.01)
        def always_fails():
            raise BrokerConnectionError("down")

        with pytest.raises(BrokerConnectionError, match="down"):
            always_fails()

    def test_does_not_retry_non_retryable_errors(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            raises_value_error()
        assert call_count == 1

    def test_custom_retryable_exceptions(self):
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, retryable=(ValueError,))
        def custom_retry():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("retry me")
            return "done"

        assert custom_retry() == "done"
        assert call_count == 3

    def test_on_retry_callback(self):
        retries = []

        @retry(
            max_attempts=3,
            base_delay=0.01,
            on_retry=lambda attempt, exc: retries.append(attempt),
        )
        def fails_twice():
            if len(retries) < 2:
                raise BrokerConnectionError("err")
            return "ok"

        assert fails_twice() == "ok"
        assert retries == [1, 2]


class TestCircuitBreaker:

    def test_starts_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            cb.record_failure(Exception("err"))
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_success_resets_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure(Exception("err"))
        cb.record_failure(Exception("err"))
        cb.record_success()
        assert cb._failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure(Exception("err"))
        cb.record_failure(Exception("err"))
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_context_manager_success(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        with cb:
            result = "ok"
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_context_manager_failure(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        with pytest.raises(ValueError):
            with cb:
                raise ValueError("boom")
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_raises(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure(Exception("err"))
        with pytest.raises(BrokerConnectionError, match="OPEN"):
            with cb:
                pass  # Should not reach here

    def test_protect_decorator(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        @cb.protect
        def my_func():
            return 42

        assert my_func() == 42
        assert cb._failure_count == 0

    def test_status_dict(self):
        cb = CircuitBreaker("mybroker", failure_threshold=5, recovery_timeout=30)
        st = cb.status()
        assert st["name"] == "mybroker"
        assert st["state"] == "CLOSED"
        assert st["failure_count"] == 0
        assert st["threshold"] == 5


class TestConfirmOrder:

    def test_confirm_traded(self):
        broker = MagicMock()
        broker.get_order_status.return_value = "TRADED"
        status = confirm_order(broker, "ORD-001", max_wait=2.0, poll_interval=0.1)
        assert status == "TRADED"

    def test_confirm_rejected_raises(self):
        broker = MagicMock()
        broker.get_order_status.return_value = "REJECTED"
        with pytest.raises(OrderPlacementError, match="REJECTED"):
            confirm_order(broker, "ORD-002", max_wait=2.0, poll_interval=0.1)

    def test_confirm_timeout(self):
        broker = MagicMock()
        broker.get_order_status.return_value = "PENDING"
        status = confirm_order(broker, "ORD-003", max_wait=0.3, poll_interval=0.1)
        assert status == "PENDING"

    def test_confirm_eventually_traded(self):
        calls = [0]

        def mock_status(orderid):
            calls[0] += 1
            if calls[0] < 3:
                return "PENDING"
            return "TRADED"

        broker = MagicMock()
        broker.get_order_status.side_effect = mock_status
        status = confirm_order(broker, "ORD-004", max_wait=5.0, poll_interval=0.1)
        assert status == "TRADED"
        assert calls[0] == 3
