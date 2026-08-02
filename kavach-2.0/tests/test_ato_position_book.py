"""Tests for position book retry (Q62)."""

from __future__ import annotations

from core.ato_position_book import read_positions_with_retry


class _FailTwiceBroker:
    def __init__(self) -> None:
        self.calls = 0

    def get_positions(self):
        self.calls += 1
        if self.calls < 3:
            raise RuntimeError("book down")
        import pandas as pd

        return pd.DataFrame([{"tradingSymbol": "SYM", "netQty": 65}])


class _AlwaysFailBroker:
    def get_positions(self):
        raise RuntimeError("book down")


def test_recovers_on_third_attempt():
    broker = _FailTwiceBroker()
    sym_qty, had_failure = read_positions_with_retry(broker, max_retries=3, retry_delay_seconds=0)
    assert had_failure is True
    assert sym_qty == {"SYM": 65}
    assert broker.calls == 3


def test_exhausted_returns_none():
    sym_qty, had_failure = read_positions_with_retry(
        _AlwaysFailBroker(), max_retries=3, retry_delay_seconds=0
    )
    assert sym_qty is None
    assert had_failure is True
