"""Unit tests for SEBI-safe aggressive LIMIT pricing."""

from __future__ import annotations

import pytest

from core.order_pricing import aggressive_limit_price, round_to_tick


def test_round_to_tick_buy_ceils() -> None:
    assert round_to_tick(10.01, 0.05, side="BUY") == 10.05
    assert round_to_tick(10.00, 0.05, side="BUY") == 10.00


def test_round_to_tick_sell_floors() -> None:
    assert round_to_tick(10.09, 0.05, side="SELL") == 10.05
    assert round_to_tick(10.00, 0.05, side="SELL") == 10.00


def test_aggressive_limit_buy_adds_buffer() -> None:
    # 100 * 1.10 = 110
    assert aggressive_limit_price(100.0, "BUY", buffer_pct=10.0) == 110.0


def test_aggressive_limit_sell_subtracts_buffer() -> None:
    # 100 * 0.90 = 90
    assert aggressive_limit_price(100.0, "SELL", buffer_pct=10.0) == 90.0


def test_aggressive_limit_buy_ceils_odd_ltp() -> None:
    # 45.3 * 1.10 = 49.83 → ceil to 49.85
    assert aggressive_limit_price(45.3, "BUY", buffer_pct=10.0, tick=0.05) == 49.85


def test_aggressive_limit_rejects_bad_ltp() -> None:
    with pytest.raises(ValueError):
        aggressive_limit_price(0, "BUY")


def test_ato_operator_defaults_include_limit_knobs() -> None:
    from core.ato_operator_config import ato_operator_settings

    s = ato_operator_settings(None)
    assert s["limit_buffer_pct"] == 10.0
    assert s["limit_tick_size"] == 0.05
    assert s["limit_chase_timeout_sec"] == 45.0
    assert s["limit_chase_interval_sec"] == 5.0
