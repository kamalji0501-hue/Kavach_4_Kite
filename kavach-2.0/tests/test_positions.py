"""Tests for core.positions helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.exceptions import BrokerAuthError, PositionError
from core.positions import (
    build_ato_protect_symbol,
    fetch_positions_rest,
    filter_nifty_positions,
    format_position_summary,
    parse_position_expiry,
)


def test_filter_nifty_positions_compact_symbol() -> None:
    df = pd.DataFrame(
        [
            {
                "tradingSymbol": "NIFTY25APR24800CE",
                "netQty": 65,
                "avgPrice": 120.5,
                "securityId": "12345",
            },
            {
                "tradingSymbol": "NIFTY25APR24700PE",
                "netQty": -130,
                "buyAvg": 80.0,
                "securityId": "67890",
            },
            {"tradingSymbol": "RELIANCE", "netQty": 10, "avgPrice": 2500.0},
            {"tradingSymbol": "NIFTY25APR24800CE", "netQty": 0, "avgPrice": 0.0},
        ]
    )
    out = filter_nifty_positions(df)
    assert len(out) == 2
    assert out[0]["symbol"] == "NIFTY25APR24700PE"
    assert out[0]["direction"] == "SHORT"
    assert out[0]["qty"] == 130
    assert out[0]["strike"] == 24700
    assert out[1]["symbol"] == "NIFTY25APR24800CE"
    assert out[1]["direction"] == "LONG"
    assert out[1]["strike"] == 24800


def test_filter_nifty_positions_hyphenated_dhan_symbol() -> None:
    """Dhan REST returns symbols like NIFTY-Jun2026-23700-PE."""
    df = pd.DataFrame(
        [
            {
                "tradingSymbol": "NIFTY-Jun2026-23700-PE",
                "netQty": -1820,
                "costPrice": 27.0,
                "securityId": "57039",
                "drvStrikePrice": 23700.0,
            }
        ]
    )
    out = filter_nifty_positions(df)
    assert len(out) == 1
    assert out[0]["opt_type"] == "PE"
    assert out[0]["direction"] == "SHORT"
    assert out[0]["qty"] == 1820
    assert out[0]["strike"] == 23700


def test_filter_nifty_positions_empty() -> None:
    assert filter_nifty_positions(None) == []
    assert filter_nifty_positions(pd.DataFrame()) == []


def test_format_position_summary_empty() -> None:
    assert "No open" in format_position_summary([])


@patch("core.positions.httpx.get")
def test_fetch_positions_rest_ok(mock_get) -> None:
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: [
            {"tradingSymbol": "NIFTY-Jun2026-24250-CE", "netQty": 910, "securityId": "1"}
        ],
    )
    df = fetch_positions_rest("1106926362", "jwt")
    assert len(df) == 1
    assert df.iloc[0]["tradingSymbol"] == "NIFTY-Jun2026-24250-CE"


def test_fetch_positions_rest_missing_credentials() -> None:
    with pytest.raises(BrokerAuthError):
        fetch_positions_rest("", "jwt")


@patch("core.positions.httpx.get")
def test_fetch_positions_rest_http_error(mock_get) -> None:
    mock_get.return_value = MagicMock(
        status_code=401,
        text='{"remarks":{"error_message":"Invalid Token"}}',
        json=lambda: {"remarks": {"error_message": "Invalid Token"}},
    )
    with pytest.raises(PositionError, match="Invalid Token"):
        fetch_positions_rest("1106926362", "bad-jwt")


def test_build_ato_protect_symbol_hyphenated() -> None:
    sell = "NIFTY-Jun2026-23700-PE"
    assert build_ato_protect_symbol(sell, 23650, "PE") == "NIFTY-Jun2026-23650-PE"
    assert build_ato_protect_symbol("NIFTY-Jun2026-24300-CE", 24350, "CE") == (
        "NIFTY-Jun2026-24350-CE"
    )


def test_build_ato_protect_symbol_compact() -> None:
    assert build_ato_protect_symbol("NIFTY25APR23700PE", 23650, "PE") == "NIFTY25APR23650PE"


def test_parse_position_expiry_from_drv_date() -> None:
    row = {"drvExpiryDate": "2026-06-02"}
    assert parse_position_expiry(row, "NIFTY-Jun2026-23700-PE") == "02 Jun 2026"


def test_parse_position_expiry_from_symbol() -> None:
    assert parse_position_expiry({}, "NIFTY-Jun2026-23700-PE") == "01 Jun 2026"
