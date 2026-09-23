"""Dhan custom-symbol mapping (no broker, no orders)."""

from datetime import date

from core.dhan_instruments import (
    dhan_custom_symbol_from_any,
    format_dhan_custom,
    last_tuesday,
)


def test_last_tuesday_matches_nse_2026() -> None:
    assert last_tuesday(2026, 8) == date(2026, 8, 25)
    assert last_tuesday(2026, 9) == date(2026, 9, 29)
    assert last_tuesday(2026, 10) == date(2026, 10, 27)


def test_kite_weekly_compact_to_dhan_custom() -> None:
    assert dhan_custom_symbol_from_any("NIFTY2690824000CE") == "NIFTY 08 SEP 24000 CALL"
    assert dhan_custom_symbol_from_any("NIFTY2690824000PE") == "NIFTY 08 SEP 24000 PUT"
    assert dhan_custom_symbol_from_any("NIFTY2692225000CE") == "NIFTY 22 SEP 25000 CALL"


def test_kite_oct_weekly_letter() -> None:
    assert dhan_custom_symbol_from_any("NIFTY26O0824000PE") == "NIFTY 08 OCT 24000 PUT"


def test_kite_monthly_uses_last_tuesday() -> None:
    assert dhan_custom_symbol_from_any("NIFTY26SEP24000CE") == "NIFTY 29 SEP 24000 CALL"
    assert dhan_custom_symbol_from_any("NIFTY26AUG25000PE") == "NIFTY 25 AUG 25000 PUT"


def test_already_dhan_custom_normalises() -> None:
    assert dhan_custom_symbol_from_any("nifty 8 sep 24000 call") == "NIFTY 08 SEP 24000 CALL"
    assert dhan_custom_symbol_from_any("NIFTY 08 SEP 24000 CE") == "NIFTY 08 SEP 24000 CALL"


def test_index_passthrough() -> None:
    assert dhan_custom_symbol_from_any("NIFTY") == "NIFTY"


def test_format_helper() -> None:
    assert format_dhan_custom(date(2026, 9, 8), 23950, "PE") == "NIFTY 08 SEP 23950 PUT"
