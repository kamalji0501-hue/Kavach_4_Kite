"""Unit tests for backtest_engine instrument resolver (offline CSV slice)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from backtest_engine.resolver.instrument_master import (
    list_nifty_option_expiries,
    resolve_fixture_trading_expiry,
    resolve_nifty_option,
)


def _mini_master() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "UNDERLYING_SYMBOL": "NIFTY",
                "INSTRUMENT": "OPTIDX",
                "SM_EXPIRY_DATE": "2026-06-09",
                "STRIKE_PRICE": 23800.0,
                "OPTION_TYPE": "CE",
                "SYMBOL_NAME": "NIFTY-Jun2026-23800-CE",
                "SECURITY_ID": 42318,
                "LOT_SIZE": 65,
            },
            {
                "UNDERLYING_SYMBOL": "NIFTY",
                "INSTRUMENT": "OPTIDX",
                "SM_EXPIRY_DATE": "2026-06-09",
                "STRIKE_PRICE": 23150.0,
                "OPTION_TYPE": "PE",
                "SYMBOL_NAME": "NIFTY-Jun2026-23150-PE",
                "SECURITY_ID": 42279,
                "LOT_SIZE": 65,
            },
        ]
    )


def test_resolve_nifty_option_mini_master() -> None:
    master = _mini_master()
    ce = resolve_nifty_option(
        strike=23800, option_type="CE", expiry_date=date(2026, 6, 9), master=master
    )
    assert ce.trading_symbol == "NIFTY-Jun2026-23800-CE"
    assert ce.security_id == "42318"
    assert ce.lot_size == 65

    pe = resolve_nifty_option(
        strike=23150, option_type="PE", expiry_date=date(2026, 6, 9), master=master
    )
    assert pe.trading_symbol == "NIFTY-Jun2026-23150-PE"


def test_list_nifty_option_expiries_filters_past() -> None:
    master = _mini_master()
    expiries = list_nifty_option_expiries(master=master, on_or_after=date(2026, 6, 9))
    assert expiries == [date(2026, 6, 9)]
    assert list_nifty_option_expiries(master=master, on_or_after=date(2026, 6, 10)) == []


def test_resolve_fixture_trading_expiry_rolls_past_fixture() -> None:
    master = pd.DataFrame(
        [
            {
                "UNDERLYING_SYMBOL": "NIFTY",
                "INSTRUMENT": "OPTIDX",
                "SM_EXPIRY_DATE": "2026-06-09",
                "STRIKE_PRICE": 23500.0,
                "OPTION_TYPE": "PE",
                "SYMBOL_NAME": "NIFTY-Jun2026-23500-PE",
                "SECURITY_ID": 42280,
                "LOT_SIZE": 65,
            },
            {
                "UNDERLYING_SYMBOL": "NIFTY",
                "INSTRUMENT": "OPTIDX",
                "SM_EXPIRY_DATE": "2026-06-25",
                "STRIKE_PRICE": 23500.0,
                "OPTION_TYPE": "PE",
                "SYMBOL_NAME": "NIFTY-Jun2026-23500-PE",
                "SECURITY_ID": 52280,
                "LOT_SIZE": 65,
            },
        ]
    )
    legs = [{"strike": 23500, "type": "PE"}]
    exp, rolled = resolve_fixture_trading_expiry(
        date(2026, 6, 23),
        legs,
        master=master,
        today=date(2026, 6, 25),
    )
    assert rolled is True
    assert exp == date(2026, 6, 25)
