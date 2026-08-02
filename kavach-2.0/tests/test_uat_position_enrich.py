"""UAT position display and price enrich."""

from __future__ import annotations

from core.uat_position_enrich import (
    enrich_nifty_positions,
    format_expiry_display,
    format_position_symbol_display,
)


def test_format_expiry_iso() -> None:
    assert format_expiry_display("2026-06-09") == "09 Jun 2026"


def test_format_symbol_display() -> None:
    sym = format_position_symbol_display("NIFTY-Jun2026-23400-CE", "09 Jun 2026")
    assert sym == "NIFTY 09 Jun 2026 23400 CE"


def test_enrich_fills_missing_avg_from_fixture() -> None:
    fixture = {
        "expiry_date": "2026-06-09",
        "legs": [
            {"strike": 23400, "type": "CE", "avg_price": 191.8},
        ],
    }
    positions = [
        {
            "symbol": "NIFTY-Jun2026-23400-CE",
            "strike": 23400,
            "opt_type": "CE",
            "direction": "SHORT",
            "qty": 130,
            "avg_price": 0.0,
            "expiry": "Jun2026",
        }
    ]
    out = enrich_nifty_positions(positions, fixture=fixture, chain_broker=None)
    assert out[0]["avg_price"] == 191.8
    assert out[0]["expiry"] == "09 Jun 2026"
    assert "09 Jun 2026" in out[0]["display_symbol"]


def test_enrich_prod_keeps_broker_avg_fills_only_missing() -> None:
    """Prod path: Dhan avg is sacred; exact-leg marketfeed only for gaps (no ×50 chain)."""
    positions = [
        {
            "symbol": "NIFTY-Jun2026-23400-CE",
            "strike": 23400,
            "opt_type": "CE",
            "direction": "SHORT",
            "qty": 130,
            "avg_price": 173.2,
            "expiry": "09 Jun 2026",
        },
        {
            "symbol": "NIFTY-Jun2026-23450-CE",
            "strike": 23450,
            "opt_type": "CE",
            "direction": "LONG",
            "qty": 65,
            "avg_price": 0.0,
            "expiry": "09 Jun 2026",
        },
    ]
    broker = type(
        "MockBroker",
        (),
        {
            "get_nifty_option_ltps": lambda self, legs, expiry_date=None: {
                (23450, "CE"): 152.0,
            },
        },
    )()
    out = enrich_nifty_positions(positions, fixture=None, chain_broker=broker)
    assert out[0]["avg_price"] == 173.2
    assert out[1]["avg_price"] == 152.0
    assert "23450 CE" in out[1]["display_symbol"]
