"""Dynamic NIFTY expiry parsing (any weekly, not hardcoded)."""

from __future__ import annotations

from datetime import date

from core.nifty_option_expiry import (
    fixture_expiry_date,
    legs_from_fixture,
    parse_dhan_trading_symbol,
    parse_expiry_label,
    trading_symbol_matches_expiry,
)


def test_parse_expiry_label_with_year() -> None:
    assert parse_expiry_label("16 Jun 2026") == date(2026, 6, 16)
    assert parse_expiry_label("2026-06-16") == date(2026, 6, 16)


def test_parse_dhan_symbol_and_expiry_match() -> None:
    exp, strike, opt = parse_dhan_trading_symbol("NIFTY-Jul2026-24000-CE")
    assert exp == date(2026, 7, 1)
    assert strike == 24000
    assert opt == "CE"
    assert trading_symbol_matches_expiry("NIFTY-Jul2026-24000-CE", date(2026, 7, 16))
    assert not trading_symbol_matches_expiry("NIFTY-Jun2026-24000-CE", date(2026, 7, 16))


def test_fixture_expiry_from_label() -> None:
    fx = {
        "expiry_label": "23 Jun 2026",
        "legs": [
            {"strike": 24000, "type": "CE", "side": "SELL", "lots": 1, "avg_price": 10.0},
        ],
    }
    assert fixture_expiry_date(fx) == date(2026, 6, 23)
    assert legs_from_fixture(fx) == [(24000, "CE")]
