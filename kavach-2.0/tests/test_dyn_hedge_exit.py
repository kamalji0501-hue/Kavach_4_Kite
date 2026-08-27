"""Unit tests for 30% dynamic hedge exit on any ATO trigger while live qty > 0."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock


class TestDynHedgeExit:
    def _make_mod(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        return ATOProtection(mock_broker, config, state, event_bus)

    def test_skips_when_disabled(self, mock_broker, config, state, event_bus):
        mod = self._make_mod(mock_broker, config, state, event_bus)
        state.set("dyn_hedge.exit_enabled", False)
        state.set(
            "positions.pe_dyn_hedge",
            {"symbol": "NIFTY28JUL2623000PE", "qty": 455, "avg_price": 4.45},
        )
        mod._position_qty = MagicMock(return_value=455)
        mod._place_ato_aggressive_limit = MagicMock(return_value="OID1")
        mod._maybe_exit_dyn_hedge("PE")
        mod._place_ato_aggressive_limit.assert_not_called()

    def test_exits_when_toggle_on_and_live_qty(self, mock_broker, config, state, event_bus):
        mod = self._make_mod(mock_broker, config, state, event_bus)
        state.set("dyn_hedge.exit_enabled", True)
        state.set(
            "positions.pe_dyn_hedge",
            {"symbol": "NIFTY28JUL2623000PE", "qty": 455, "avg_price": 4.45},
        )
        mod._position_qty = MagicMock(return_value=455)
        mod._place_ato_aggressive_limit = MagicMock(return_value="OID-DH")
        mod._maybe_exit_dyn_hedge("PE")
        mod._place_ato_aggressive_limit.assert_called_once_with(
            symbol="NIFTY28JUL2623000PE",
            qty=455,
            side="SELL",
            product=config.get("strategy.product_type", "MARGIN"),
        )
        assert state.get("dyn_hedge.pe_exited_date") == date.today().isoformat()

        # Still long — next ATO fire sells remaining
        mod._place_ato_aggressive_limit.reset_mock()
        mod._position_qty = MagicMock(return_value=65)
        mod._maybe_exit_dyn_hedge("PE")
        mod._place_ato_aggressive_limit.assert_called_once_with(
            symbol="NIFTY28JUL2623000PE",
            qty=65,
            side="SELL",
            product=config.get("strategy.product_type", "MARGIN"),
        )

        # Flat — skip (do not short)
        mod._place_ato_aggressive_limit.reset_mock()
        mod._position_qty = MagicMock(return_value=0)
        mod._maybe_exit_dyn_hedge("PE")
        mod._place_ato_aggressive_limit.assert_not_called()

    def test_skips_when_leg_missing(self, mock_broker, config, state, event_bus):
        mod = self._make_mod(mock_broker, config, state, event_bus)
        state.set("dyn_hedge.exit_enabled", True)
        state.set("positions.pe_dyn_hedge", None)
        mod._place_ato_aggressive_limit = MagicMock(return_value="OID1")
        mod._maybe_exit_dyn_hedge("PE")
        mod._place_ato_aggressive_limit.assert_not_called()

    def test_ce_side_independent(self, mock_broker, config, state, event_bus):
        mod = self._make_mod(mock_broker, config, state, event_bus)
        state.set("dyn_hedge.exit_enabled", True)
        state.set(
            "positions.ce_dyn_hedge",
            {"symbol": "NIFTY28JUL2625000CE", "qty": 455, "avg_price": 2.95},
        )
        mod._position_qty = MagicMock(return_value=455)
        mod._place_ato_aggressive_limit = MagicMock(return_value="OID-CE")
        mod._maybe_exit_dyn_hedge("CE")
        mod._place_ato_aggressive_limit.assert_called_once()
        assert state.get("dyn_hedge.ce_exited_date") == date.today().isoformat()
        assert state.get("dyn_hedge.pe_exited_date") in (None, "")
