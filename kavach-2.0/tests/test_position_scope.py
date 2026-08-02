"""Tests for core.position_scope."""

from __future__ import annotations

from core.position_scope import (
    DEFAULT_LOT_SIZE,
    build_registration_scope,
    legacy_registration_scope_from_deployment,
    max_managed_lots,
    max_managed_lots_flexible,
    parse_and_validate_ato_lots,
    resolve_nifty_lot_size,
    scale_side,
    scale_side_flexible,
    side_lots_selection,
    suggested_ato_lots,
    validate_side_ratio,
)


def test_validate_side_ratio_ok():
    ok, msg = validate_side_ratio(910, 1820, lot_size=65)
    assert ok is True
    assert msg == ""


def test_validate_side_ratio_fail():
    ok, msg = validate_side_ratio(910, 910, lot_size=65)
    assert ok is False
    assert "1:2" in msg


def test_max_managed_lots():
    assert max_managed_lots(910, 1820, lot_size=65) == 14


def test_scale_side():
    buy = {"symbol": "NIFTY-PE", "qty": 910, "direction": "LONG", "strike": 23750}
    sell = {"symbol": "NIFTY-PE-S", "qty": 1820, "direction": "SHORT", "strike": 23700}
    mb, ms = scale_side(buy, sell, 7, lot_size=65)
    assert mb["qty"] == 455
    assert mb["broker_qty"] == 910
    assert ms["qty"] == 910
    assert ms["broker_qty"] == 1820
    assert ms["direction"] == "SHORT"


def test_build_registration_scope():
    scope = build_registration_scope(
        pe_enabled=True, ce_enabled=False, pe_managed_lots=14, ce_managed_lots=None
    )
    assert scope["pe_enabled"] is True
    assert scope["ce_enabled"] is False


def test_scale_side_flexible_proportional():
    buy = {"symbol": "NIFTY-CE", "qty": 910, "direction": "LONG", "strike": 24250}
    sell = {"symbol": "NIFTY-CE-S", "qty": 3770, "direction": "SHORT", "strike": 25000}
    mb, ms = scale_side_flexible(buy, sell, 7, lot_size=65)
    assert mb["qty"] == 455
    assert mb["broker_qty"] == 910
    assert ms["qty"] == 1885
    assert ms["broker_qty"] == 3770


def test_max_managed_lots_flexible_non_ratio():
    assert max_managed_lots_flexible(910, 910, lot_size=65) == 14
    assert max_managed_lots_flexible(910, 3770, lot_size=65) == 14


def test_resolve_nifty_lot_size_rejects_bad_broker():
    assert resolve_nifty_lot_size(broker_lot_size=1) == DEFAULT_LOT_SIZE
    assert resolve_nifty_lot_size(config_lot_size=65, broker_lot_size=1) == 65


def test_side_lots_selection():
    max_l, buy_l, sell_l, lot = side_lots_selection(910, 1820, lot_size=65)
    assert max_l == 14
    assert buy_l == 14
    assert sell_l == 28
    assert lot == 65


def test_legacy_scope_from_old_deployment():
    dep = {
        "positions": {
            "pe_buy": {"qty": 910},
            "pe_sell": {"qty": 1820},
            "ce_buy": {"qty": 910},
            "ce_sell": {"qty": 1820},
        }
    }
    scope = legacy_registration_scope_from_deployment(dep)
    assert scope["pe_enabled"] is True
    assert scope["ce_enabled"] is True
    assert scope["pe_managed_lots"] == 14
    assert scope["pe_ato_lots"] == 14
    assert scope["ce_ato_lots"] == 14


def test_parse_and_validate_ato_lots():
    assert parse_and_validate_ato_lots("0") == (0, None)
    assert parse_and_validate_ato_lots(" 12 ") == (12, None)
    assert parse_and_validate_ato_lots("")[1]
    assert parse_and_validate_ato_lots("-1")[1]
    assert parse_and_validate_ato_lots("3.5")[1]
    assert parse_and_validate_ato_lots("abc")[1]


def test_suggested_ato_lots():
    assert suggested_ato_lots(6, 390, lot_size=65) == 6
    assert suggested_ato_lots(None, 390, lot_size=65) == 6


def test_build_registration_scope_ato_lots():
    scope = build_registration_scope(
        pe_enabled=True,
        ce_enabled=True,
        pe_managed_lots=6,
        ce_managed_lots=8,
        pe_ato_lots=4,
        ce_ato_lots=0,
    )
    assert scope["schema_version"] == 2
    assert scope["pe_ato_lots"] == 4
    assert scope["ce_ato_lots"] == 0


def test_auto_protect_strike():
    from core.position_scope import auto_protect_strike

    assert auto_protect_strike(24000, "CE", ato_step=50) == 24050
    assert auto_protect_strike(23600, "PE", ato_step=50) == 23550


def test_parse_and_validate_protect_strike():
    from core.position_scope import parse_and_validate_protect_strike

    assert parse_and_validate_protect_strike("24050") == (24050, None)
    assert parse_and_validate_protect_strike("24100") == (24100, None)
    assert parse_and_validate_protect_strike("24025")[1]
    assert parse_and_validate_protect_strike("24050.5")[1]


def test_protect_strike_direction_warnings():
    from core.position_scope import protect_strike_direction_warnings

    assert protect_strike_direction_warnings("CE", 24000, 24050) == []
    assert protect_strike_direction_warnings("CE", 24000, 24000)
    assert protect_strike_direction_warnings("PE", 23600, 23600)
