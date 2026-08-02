"""Tests for cache-first market data guards."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.market_data_guard import (
    allow_live_option_quotes,
    legs_still_missing_after_fixture,
    positions_fingerprint,
    should_skip_live_quotes,
)
from core.uat_position_enrich import enrich_nifty_positions


def test_should_skip_when_fixture_has_all_prices() -> None:
    fixture = {
        "expiry_date": "2026-06-09",
        "legs": [
            {"strike": 23400, "type": "CE", "avg_price": 171.0},
            {"strike": 23450, "type": "CE", "avg_price": 152.0},
        ],
    }
    positions = [
        {"symbol": "NIFTY-Jun2026-23400-CE", "strike": 23400, "opt_type": "CE", "avg_price": 0},
        {"symbol": "NIFTY-Jun2026-23450-CE", "strike": 23450, "opt_type": "CE", "avg_price": 0},
    ]
    skip, reason = should_skip_live_quotes(positions, fixture=fixture)
    assert skip is True
    assert "fixture" in reason


def test_enrich_never_calls_broker_when_fixture_complete() -> None:
    fixture = {
        "expiry_date": "2026-06-09",
        "legs": [{"strike": 23400, "type": "CE", "avg_price": 191.8}],
    }
    positions = [
        {
            "symbol": "NIFTY-Jun2026-23400-CE",
            "strike": 23400,
            "opt_type": "CE",
            "avg_price": 0,
        }
    ]
    broker = MagicMock()
    broker.get_nifty_option_ltps = MagicMock(return_value={})
    out = enrich_nifty_positions(positions, fixture=fixture, chain_broker=broker)
    assert out[0]["avg_price"] == 191.8
    broker.get_nifty_option_ltps.assert_not_called()


def test_quote_throttle_blocks_burst() -> None:
    assert allow_live_option_quotes(leg_count=2) is True
    assert allow_live_option_quotes(leg_count=2) is False


def test_fingerprint_stable() -> None:
    pos = [{"symbol": "A", "qty": 1, "strike": 100, "avg_price": 1.0}]
    assert positions_fingerprint(pos) == positions_fingerprint(pos)


def test_legs_still_missing_after_fixture() -> None:
    fixture = {"legs": [{"strike": 23400, "type": "CE", "avg_price": 10.0}]}
    positions = [
        {"strike": 23400, "opt_type": "CE", "avg_price": 0},
        {"strike": 23500, "opt_type": "CE", "avg_price": 0},
    ]
    need = legs_still_missing_after_fixture(positions, fixture)
    assert (23400, "CE") not in need
    assert (23500, "CE") in need
