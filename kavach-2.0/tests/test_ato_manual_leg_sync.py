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
            entry_pending=False,
            consecutive_zero_polls=3,
            min_zero_polls_for_halt=3,
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


    def test_26a_adopt_when_triggered_but_inactive(self):
        """Re-Register can leave triggered=True with ato_active=False and leftover qty."""
        result = evaluate_side_manual_sync(
            side="PE",
            protect_symbol="NIFTY2690823650PE",
            expected_qty=65,
            triggered=True,
            ato_active=False,
            broker_qty=65,
            side_halted=False,
        )
        assert result is not None
        assert result.action == "adopt_idle"

    def test_26a_adopt_when_expected_qty_zero_but_broker_long(self):
        result = evaluate_side_manual_sync(
            side="PE",
            protect_symbol="NIFTY2690823650PE",
            expected_qty=0,
            triggered=False,
            ato_active=False,
            broker_qty=65,
            side_halted=False,
        )
        assert result is not None
        assert result.action == "adopt_idle"
        assert result.expected_qty == 65


    def test_fill_pending_blocks_full_exit_even_if_seen(self):
        """Today bug: prior-cycle seen + post-BUY qty=0 must not halt during grace."""
        result = evaluate_side_manual_sync(
            side="PE",
            protect_symbol="NIFTY2691523800PE",
            expected_qty=65,
            triggered=True,
            ato_active=True,
            broker_qty=0,
            side_halted=False,
            protect_seen_at_broker=True,
            entry_pending=True,
            consecutive_zero_polls=5,
        )
        assert result is not None
        assert result.action == "fill_pending"

    def test_await_zero_confirm_before_full_exit(self):
        result = evaluate_side_manual_sync(
            side="PE",
            protect_symbol="NIFTY2691523800PE",
            expected_qty=65,
            triggered=True,
            ato_active=True,
            broker_qty=0,
            side_halted=False,
            protect_seen_at_broker=True,
            entry_pending=False,
            consecutive_zero_polls=1,
            min_zero_polls_for_halt=3,
        )
        assert result is not None
        assert result.action == "await_zero_confirm"

    def test_full_exit_after_confirmed_zeros(self):
        result = evaluate_side_manual_sync(
            side="PE",
            protect_symbol="NIFTY2691523800PE",
            expected_qty=65,
            triggered=True,
            ato_active=True,
            broker_qty=0,
            side_halted=False,
            protect_seen_at_broker=True,
            entry_pending=False,
            consecutive_zero_polls=3,
            min_zero_polls_for_halt=3,
        )
        assert result is not None
        assert result.action == "pause_full_exit"

    def test_no_halt_when_never_seen_this_cycle(self):
        result = evaluate_side_manual_sync(
            side="PE",
            protect_symbol="NIFTY2691523800PE",
            expected_qty=65,
            triggered=True,
            ato_active=True,
            broker_qty=0,
            side_halted=False,
            protect_seen_at_broker=False,
            entry_pending=False,
            consecutive_zero_polls=10,
        )
        assert result is None

    def test_partial_exit_blocked_during_entry_pending(self):
        result = evaluate_side_manual_sync(
            side="CE",
            protect_symbol="NIFTY CALL",
            expected_qty=130,
            triggered=True,
            ato_active=True,
            broker_qty=65,
            side_halted=False,
            protect_seen_at_broker=True,
            entry_pending=True,
        )
        assert result is not None
        assert result.action == "fill_pending"
