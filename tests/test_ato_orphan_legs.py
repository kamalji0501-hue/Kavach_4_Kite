"""Tests for orphan leg detection (Q59)."""

from __future__ import annotations

from core.ato_orphan_legs import detect_orphan_long_legs, registered_symbol_set


def test_detect_orphan_long():
    registered = registered_symbol_set(
        {
            "ce_buy": {"symbol": "NIFTY CE BUY"},
            "ce_sell": {"symbol": "NIFTY CE SELL"},
        },
        ce_protect_symbol="NIFTY CE PROTECT",
    )
    warnings = detect_orphan_long_legs(
        [
            {"tradingSymbol": "NIFTY CE PROTECT", "netQty": 65},
            {"tradingSymbol": "NIFTY OLD CE", "netQty": 130},
        ],
        registered,
    )
    assert len(warnings) == 1
    assert "NIFTY OLD CE" in warnings[0]


def test_registered_protect_not_orphan():
    registered = registered_symbol_set(
        {"ce_sell": {"symbol": "NIFTY CE SELL"}},
        ce_protect_symbol="NIFTY CE PROTECT",
    )
    warnings = detect_orphan_long_legs(
        [{"tradingSymbol": "NIFTY CE PROTECT", "netQty": 65}],
        registered,
    )
    assert warnings == []
