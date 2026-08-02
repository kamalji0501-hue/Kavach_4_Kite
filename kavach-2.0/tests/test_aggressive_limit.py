"""Tests for BatmanBroker.place_aggressive_limit chase loop."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.broker import BatmanBroker
from core.exceptions import OrderPlacementError


def _broker_with_tsl(tsl) -> BatmanBroker:
    return BatmanBroker(tsl, client_code="C1", access_token="T1")


def test_place_aggressive_limit_buys_above_ltp_and_fills() -> None:
    tsl = MagicMock()
    tsl.get_ltp_data.return_value = {"NIFTY02JUN2624000CE": 40.0}
    tsl.order_placement.return_value = "OID-1"
    tsl.get_order_status.return_value = "TRADED"

    broker = _broker_with_tsl(tsl)
    oid = broker.place_aggressive_limit(
        symbol="NIFTY02JUN2624000CE",
        qty=65,
        side="BUY",
        buffer_pct=10.0,
        tick_size=0.05,
        chase_timeout_sec=2.0,
        chase_interval_sec=10.0,  # no chase needed
    )
    assert oid == "OID-1"
    kwargs = tsl.order_placement.call_args.kwargs
    assert kwargs["order_type"] == "LIMIT"
    assert kwargs["transaction_type"] == "BUY"
    assert kwargs["price"] == 44.0  # 40 * 1.10


def test_place_aggressive_limit_chases_then_fills() -> None:
    tsl = MagicMock()
    # Rising LTP → rising SELL limit after buffer → chase modify fires.
    tsl.get_ltp_data.side_effect = [
        {"SYM": 50.0},  # initial place → 45.0
        {"SYM": 60.0},  # chase → 54.0
    ]
    tsl.order_placement.return_value = "OID-2"
    tsl.get_order_status.side_effect = ["PENDING", "PENDING", "TRADED"]
    tsl.modify_order.return_value = "OK"

    broker = _broker_with_tsl(tsl)
    oid = broker.place_aggressive_limit(
        symbol="SYM",
        qty=65,
        side="SELL",
        buffer_pct=10.0,
        chase_timeout_sec=3.0,
        chase_interval_sec=0.01,
    )
    assert oid == "OID-2"
    assert tsl.modify_order.called
    mod_kw = tsl.modify_order.call_args.kwargs
    assert mod_kw["price"] == 54.0  # 60 * 0.90


def test_place_aggressive_limit_timeout_cancels() -> None:
    tsl = MagicMock()
    tsl.get_ltp_data.return_value = {"SYM": 50.0}
    tsl.order_placement.return_value = "OID-3"
    tsl.get_order_status.return_value = "PENDING"
    tsl.cancel_order.return_value = "CANCELLED"

    broker = _broker_with_tsl(tsl)
    with pytest.raises(OrderPlacementError, match="timed out"):
        broker.place_aggressive_limit(
            symbol="SYM",
            qty=65,
            side="BUY",
            chase_timeout_sec=0.2,
            chase_interval_sec=0.05,
        )
    tsl.cancel_order.assert_called()
