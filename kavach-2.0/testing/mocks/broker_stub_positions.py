"""
Batman v3 — Mock broker position DataFrame builder.

Usage in tests:
    from testing.mocks.broker_stub_positions import make_positions_df, POSITIONS_APR7

    mock_broker._positions = make_positions_df(POSITIONS_APR7)

This builds a pd.DataFrame matching the shape Dhan Tradehull returns
for broker.get_positions() (or equivalent).
"""

from __future__ import annotations

import pandas as pd

# ── Real April 7, 2026 positions (from screenshot) ───────────────────────────

POSITIONS_APR7 = [
    {
        "symbol": "NIFTY07APR22000PE",
        "netQty": -1560,  # negative = SHORT
        "buyAvg": 0.0,
        "sellAvg": 87.00,
        "ltp": 72.00,
        "unrealizedProfit": 23400.00,
        "drvOptionType": "PUT",
        "drvStrikePrice": 22000.0,
        "drvExpiryDate": "2026-04-07",
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "securityId": "51234",
    },
    {
        "symbol": "NIFTY07APR22050PE",
        "netQty": 780,  # positive = LONG
        "buyAvg": 95.19,
        "sellAvg": 0.0,
        "ltp": 79.05,
        "unrealizedProfit": -12587.25,
        "drvOptionType": "PUT",
        "drvStrikePrice": 22050.0,
        "drvExpiryDate": "2026-04-07",
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "securityId": "51235",
    },
    {
        "symbol": "NIFTY07APR23150CE",
        "netQty": 780,  # positive = LONG
        "buyAvg": 88.09,
        "sellAvg": 0.0,
        "ltp": 83.50,
        "unrealizedProfit": -3578.25,
        "drvOptionType": "CALL",
        "drvStrikePrice": 23150.0,
        "drvExpiryDate": "2026-04-07",
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "securityId": "51236",
    },
    {
        "symbol": "NIFTY07APR23200CE",
        "netQty": -1560,  # negative = SHORT
        "buyAvg": 0.0,
        "sellAvg": 76.00,
        "ltp": 71.10,
        "unrealizedProfit": 7644.00,
        "drvOptionType": "CALL",
        "drvStrikePrice": 23200.0,
        "drvExpiryDate": "2026-04-07",
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "securityId": "51237",
    },
]


def make_positions_df(rows: list[dict]) -> pd.DataFrame:
    """Build a broker-shaped positions DataFrame from a list of dicts.

    Args:
        rows: List of position dicts (see POSITIONS_APR7 above).

    Returns:
        pd.DataFrame with all columns Dhan Tradehull returns.
    """
    return pd.DataFrame(rows)


# ── Convenience pre-built DataFrames ─────────────────────────────────────────


def positions_apr7_df() -> pd.DataFrame:
    """Ready-to-use DataFrame for Apr 7 positions (all 4 legs)."""
    return make_positions_df(POSITIONS_APR7)


def positions_ce_side_only() -> pd.DataFrame:
    """Only CE legs — for testing CE-only ATO scenarios."""
    return make_positions_df([r for r in POSITIONS_APR7 if r["drvOptionType"] == "CALL"])


def positions_pe_side_only() -> pd.DataFrame:
    """Only PE legs — for testing PE-only ATO scenarios."""
    return make_positions_df([r for r in POSITIONS_APR7 if r["drvOptionType"] == "PUT"])


def positions_with_ato_ce_open() -> pd.DataFrame:
    """All 4 batman legs PLUS the CE ATO protection position already open
    (simulates: ATO was manually placed before restart)."""
    ato_ce = {
        "symbol": "NIFTY07APR23250CE",
        "netQty": 1560,  # LONG (bought for protection)
        "buyAvg": 12.50,
        "sellAvg": 0.0,
        "ltp": 14.00,
        "unrealizedProfit": 2340.00,
        "drvOptionType": "CALL",
        "drvStrikePrice": 23250.0,
        "drvExpiryDate": "2026-04-07",
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "securityId": "51238",
    }
    return make_positions_df(POSITIONS_APR7 + [ato_ce])


def positions_with_ato_pe_open() -> pd.DataFrame:
    """All 4 batman legs PLUS the PE ATO protection position already open."""
    ato_pe = {
        "symbol": "NIFTY07APR21950PE",
        "netQty": 1560,  # LONG (bought for protection)
        "buyAvg": 8.75,
        "sellAvg": 0.0,
        "ltp": 7.00,
        "unrealizedProfit": -2730.00,
        "drvOptionType": "PUT",
        "drvStrikePrice": 21950.0,
        "drvExpiryDate": "2026-04-07",
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "securityId": "51239",
    }
    return make_positions_df(POSITIONS_APR7 + [ato_pe])
