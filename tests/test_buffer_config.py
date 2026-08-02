"""Tests for core.buffer_config."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.buffer_config import (
    BufferKind,
    legacy_int_from_buffer,
    normalize_buffer_field,
    parse_buffer_text,
    serialize_buffer_field,
    validate_buffer,
)
from core.buffer_config.schema import parse_and_validate_user_buffer


def test_parse_buffer_text_decimal():
    assert parse_buffer_text("2.5") == Decimal("2.5")
    assert parse_buffer_text("-200") == Decimal("-200")
    assert parse_buffer_text("0") == Decimal("0")


def test_parse_buffer_text_invalid():
    with pytest.raises(ValueError):
        parse_buffer_text("abc")


def test_validate_buffer_range():
    ok, _ = validate_buffer(Decimal("0.5"))
    assert ok is True
    ok, _ = validate_buffer(Decimal("0"))
    assert ok is True
    ok, _ = validate_buffer(Decimal("-200"))
    assert ok is True
    ok, _ = validate_buffer(Decimal("-500"))
    assert ok is True
    ok, _ = validate_buffer(Decimal("-501"))
    assert ok is False
    ok, _ = validate_buffer(Decimal("101"))
    assert ok is False


def test_serialize_and_normalize():
    field = serialize_buffer_field(Decimal("2.5"), BufferKind.CUSTOM)
    assert field["type"] == "CUSTOM"
    assert normalize_buffer_field(field) == Decimal("2.50")
    neg = serialize_buffer_field(Decimal("-200"), BufferKind.CUSTOM)
    assert normalize_buffer_field(neg) == Decimal("-200.00")


def test_normalize_preserves_decimal_roundtrip():
    """In-memory state stores Decimal after restore; must not collapse to 0."""
    once = normalize_buffer_field({"type": "CUSTOM", "value": "6"})
    assert once == Decimal("6.00")
    assert normalize_buffer_field(once) == Decimal("6.00")
    neg = normalize_buffer_field({"type": "CUSTOM", "value": "-200"})
    assert normalize_buffer_field(neg) == Decimal("-200.00")


def test_legacy_int_from_buffer():
    assert legacy_int_from_buffer(5) == 5
    assert legacy_int_from_buffer({"type": "CUSTOM", "value": "2.5"}) == 2
    assert legacy_int_from_buffer({"type": "CUSTOM", "value": "-200"}) == -200


def test_parse_and_validate_user_buffer():
    val, err = parse_and_validate_user_buffer("1.25")
    assert err is None
    assert val == Decimal("1.25")
    val, err = parse_and_validate_user_buffer("0")
    assert err is None
    assert val == Decimal("0.00")
    val, err = parse_and_validate_user_buffer("-200")
    assert err is None
    assert val == Decimal("-200.00")
    val, err = parse_and_validate_user_buffer("-500")
    assert err is None
    assert val == Decimal("-500.00")
    val, err = parse_and_validate_user_buffer("-501")
    assert val is None
    assert err is not None
    val, err = parse_and_validate_user_buffer("abc")
    assert val is None
    assert err is not None


def test_ce_pe_trigger_math_signed_buffers():
    """Engine formulas: CE strike+buf / PE strike-buf (asymmetric)."""
    sell_ce = Decimal("24300")
    sell_pe = Decimal("24150")
    entry = Decimal("-200")
    retrace = Decimal("5")

    ce_trigger = sell_ce + entry
    ce_exit = sell_ce - retrace
    pe_trigger = sell_pe - entry
    pe_exit = sell_pe + retrace

    assert ce_trigger == Decimal("24100")  # early protect for CE
    assert ce_exit == Decimal("24295")
    assert pe_trigger == Decimal("24350")  # PE: negative entry → higher trigger
    assert pe_exit == Decimal("24155")

    # Positive buffers (regression)
    assert sell_ce + Decimal("5") == Decimal("24305")
    assert sell_pe - Decimal("5") == Decimal("24145")


def test_free_signed_entry_exit_allowed():
    """No hysteresis block — any signed pair within range is accepted."""
    val, err = parse_and_validate_user_buffer("-10")
    assert err is None and val == Decimal("-10.00")
    val, err = parse_and_validate_user_buffer("-5")
    assert err is None and val == Decimal("-5.00")


def test_nifty_level_roundtrip_pe():
    from core.buffer_config.levels import (
        buffer_from_nifty_level,
        nifty_level_from_buffer,
        parse_and_validate_user_buffer_or_level,
        format_buffer_with_level,
    )

    sell = 24150
    buf = buffer_from_nifty_level(Decimal("24160"), side="PE", kind="entry", sell_strike=sell)
    assert buf == Decimal("-10")
    assert nifty_level_from_buffer(buf, side="PE", kind="entry", sell_strike=sell) == Decimal(
        "24160"
    )
    exit_buf = buffer_from_nifty_level(Decimal("24165"), side="PE", kind="exit", sell_strike=sell)
    assert exit_buf == Decimal("15")

    val, err, mode = parse_and_validate_user_buffer_or_level(
        "24160", side="PE", kind="entry", sell_strike=sell
    )
    assert err is None and mode == "level" and val == Decimal("-10.00")
    val, err, mode = parse_and_validate_user_buffer_or_level(
        "-10", side="PE", kind="entry", sell_strike=sell
    )
    assert err is None and mode == "buffer" and val == Decimal("-10.00")
    assert "24,160" in format_buffer_with_level(
        Decimal("-10"), side="PE", kind="entry", sell_strike=sell
    )


def test_nifty_level_ce_entry():
    from core.buffer_config.levels import buffer_from_nifty_level, parse_and_validate_user_buffer_or_level

    sell = 24300
    # CE early protect at 24100 → entry buffer -200
    buf = buffer_from_nifty_level(Decimal("24100"), side="CE", kind="entry", sell_strike=sell)
    assert buf == Decimal("-200")
    val, err, mode = parse_and_validate_user_buffer_or_level(
        "24100", side="CE", kind="entry", sell_strike=sell
    )
    assert mode == "level" and val == Decimal("-200.00") and err is None
