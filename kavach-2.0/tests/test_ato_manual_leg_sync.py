"""Tests for mid-session manual protect leg sync (operator bible §7)."""

from __future__ import annotations

from core.ato_manual_leg_sync import evaluate_side_manual_sync, symbol_qty_map


class TestSymbolQtyMap:
    def test_empty_dataframe(self):
        class _Empty:
            empty = True

            def iterrows(self):
                return iter([])

        assert symbol_qty_map(_Empty()) == {}

    def test_unreadable_returns_none(self):
        assert symbol_qty_map(None) is None

    def test_list_positions(self):
        rows = [{"tradingSymbol": "NIFTY CALL", "netQty": 130}]
        assert symbol_qty_map(rows) == {"NIFTY CALL": 130}

    def test_signed_short_not_abs(self):
        rows = [{"tradingSymbol": "NIFTY PUT", "netQty": -65}]
        assert symbol_qty_map(rows) == {"NIFTY PUT": -65}


class TestEvaluateSideManualSync:
    def test_26a_adopt_idle_correct_protect(self):
        result = evaluate_side_manual_sync(
            side="CE",
            protect_symbol="NIFTY 10 MAR 25550 CALL",
            expected_qty=65,
            triggered=False,
            ato_active=False,
            broker_qty=65,
            side_halted=False,
        )
        assert result is not None
        assert result.action == "adopt_idle"

    def test_26a_adopt_disabled_returns_none(self):
        result = evaluate_side_manual_sync(
            side="CE",
            protect_symbol="NIFTY 10 MAR 25550 CALL",
            expected_qty=65,
            triggered=False,
            ato_active=False,
            broker_qty=65,
            side_halted=False,
            manual_protect_adopt_enabled=False,
        )
        assert result is None

    def test_26c_wrong_strike_is_invisible(self):
        """Q50 — only registered protect symbol is evaluated; no action for stray legs."""
        result = evaluate_side_manual_sync(
            side="CE",
            protect_symbol="NIFTY 10 MAR 25550 CALL",
            expected_qty=65,
            triggered=False,
            ato_active=False,
            broker_qty=0,
            side_halted=False,
        )
        assert result is None

    def test_26d_pause_full_exit(self):
        result = evaluate_side_manual_sync(
            side="CE",
            protect_symbol="NIFTY 10 MAR 25550 CALL",
            expected_qty=65,
            triggered=True,
            ato_active=True,
            broker_qty=0,
            side_halted=False,
            protect_seen_at_broker=True,
        )
        assert result is not None
        assert result.action == "pause_full_exit"

    def test_31_pause_partial_exit(self):
        result = evaluate_side_manual_sync(
            side="PE",
            protect_symbol="NIFTY 10 MAR 24850 PUT",
            expected_qty=130,
            triggered=True,
            ato_active=True,
            broker_qty=65,
            side_halted=False,
            protect_seen_at_broker=True,
        )
        assert result is not None
        assert result.action == "pause_partial_exit"

    def test_skips_when_side_halted(self):
        result = evaluate_side_manual_sync(
            side="CE",
            protect_symbol="SYM",
            expected_qty=65,
            triggered=True,
            ato_active=True,
            broker_qty=0,
            side_halted=True,
        )
        assert result is None
