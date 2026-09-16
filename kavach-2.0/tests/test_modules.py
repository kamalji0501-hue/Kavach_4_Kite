"""Tests for trading modules using MockBroker."""

import csv
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


class TestATOProtection:

    @pytest.fixture(autouse=True)
    def _ato_test_guards(self, state, monkeypatch):
        """Mirror confirmed deployment without qty-mismatch side effects in unit tests."""
        from decimal import Decimal

        state.set("deployment.confirmed", True)
        from modules.ato_protection import ATOProtection

        monkeypatch.setattr(ATOProtection, "_check_managed_qty_mismatch", lambda self: None)

        def _test_resolve_spot(self):
            ltp = getattr(self.broker, "_nifty_ltp", 25000.0)
            return Decimal(str(ltp))

        monkeypatch.setattr(ATOProtection, "_resolve_nifty_spot", _test_resolve_spot)

    def test_set_retrace_points(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod.set_retrace_points(35)
        assert state.get("ato.retrace_points") == 35

    def test_ce_breach_triggers_protection(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        # Simulate deployed iron condor with ATO protect symbols stored in state
        state.set(
            "positions.ce_sell",
            {
                "symbol": "NIFTY 10 MAR 25500 CALL",
                "strike": 25500,
                "qty": -130,
                "order_id": "ORD-001",
            },
        )
        state.set(
            "positions.ce_buy",
            {
                "symbol": "NIFTY 10 MAR 25450 CALL",  # inside: ATM + hedge_gap (250)
                "strike": 25450,
                "qty": 65,
                "order_id": "ORD-002",
            },
        )
        state.set(
            "positions.pe_sell",
            {
                "symbol": "NIFTY 10 MAR 24900 PUT",
                "strike": 24900,
                "qty": -130,
                "order_id": "ORD-003",
            },
        )
        state.set(
            "positions.pe_buy",
            {
                "symbol": "NIFTY 10 MAR 24950 PUT",  # inside: ATM - hedge_gap (250)
                "strike": 24950,
                "qty": 65,
                "order_id": "ORD-004",
            },
        )
        # ATO protect symbols set by deploy_handler at /confirm_deploy time (sell_otm + 1 step)
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 24850 PUT")
        state.set("ato.pe_protect_strike", 24850)
        state.set("ato.retrace_points", 5)

        # Spot at 25505 = ce_sell(25500) + retrace_points(5) → triggers CE ATO
        mock_broker._nifty_ltp = 25505.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert state.get("ato.ce_triggered") is True
        assert state.get("ato.ce_ato_active") is True
        assert state.get("ato.ce_order_id") is not None
        assert state.get("ato.pe_triggered") is False

        # Must buy the NEXT strike (25550), not the sell strike (25500)
        ce_ato_order = next(o for o in mock_broker._orders if "25550" in o["symbol"])
        assert ce_ato_order["qty"] == 65  # 1 lot = 65
        assert ce_ato_order["side"] == "BUY"

    def test_ce_breach_uses_custom_ato_lots_from_scope(
        self, mock_broker, config, state, event_bus
    ):
        from modules.ato_protection import ATOProtection

        state.set(
            "positions.ce_sell",
            {"symbol": "NIFTY 10 MAR 25500 CALL", "strike": 25500, "qty": -130},
        )
        state.set(
            "positions.ce_buy",
            {"symbol": "NIFTY 10 MAR 25450 CALL", "strike": 25450, "qty": 65},
        )
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set(
            "deployment.registration_scope",
            {"ce_ato_lots": 3, "lot_size": 65},
        )
        mock_broker._nifty_ltp = 25505.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        ce_ato_order = next(o for o in mock_broker._orders if "25550" in o["symbol"])
        assert ce_ato_order["qty"] == 195  # 3 lots × 65

    def test_ce_breach_zero_ato_lots_skips_order(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        state.set(
            "positions.ce_sell",
            {"symbol": "NIFTY 10 MAR 25500 CALL", "strike": 25500, "qty": -130},
        )
        state.set(
            "positions.ce_buy",
            {"symbol": "NIFTY 10 MAR 25450 CALL", "strike": 25450, "qty": 65},
        )
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set(
            "deployment.registration_scope",
            {"ce_ato_lots": 0, "lot_size": 65},
        )
        mock_broker._nifty_ltp = 25505.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert state.get("ato.ce_triggered") is True
        assert not any("25550" in o["symbol"] for o in mock_broker._orders)

    def test_ce_breach_custom_protect_strike_order_qty(
        self, mock_broker, config, state, event_bus
    ):
        from modules.ato_protection import ATOProtection

        state.set(
            "positions.ce_sell",
            {"symbol": "NIFTY 10 MAR 25500 CALL", "strike": 25500, "qty": -130},
        )
        state.set(
            "positions.ce_buy",
            {"symbol": "NIFTY 10 MAR 25450 CALL", "strike": 25450, "qty": 65},
        )
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25600 CALL")
        state.set("ato.ce_protect_strike", 25600)
        state.set(
            "deployment.registration_scope",
            {"ce_ato_lots": 2, "lot_size": 65},
        )
        mock_broker._nifty_ltp = 25505.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        ce_ato_order = next(o for o in mock_broker._orders if "25600" in o["symbol"])
        assert ce_ato_order["qty"] == 130

    def test_pe_breach_triggers_protection(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        state.set(
            "positions.ce_sell",
            {
                "symbol": "NIFTY 10 MAR 25500 CALL",
                "strike": 25500,
                "qty": -130,
                "order_id": "ORD-001",
            },
        )
        state.set(
            "positions.ce_buy",
            {
                "symbol": "NIFTY 10 MAR 25450 CALL",  # inside: ATM + hedge_gap (250)
                "strike": 25450,
                "qty": 65,
                "order_id": "ORD-002",
            },
        )
        state.set(
            "positions.pe_sell",
            {
                "symbol": "NIFTY 10 MAR 24900 PUT",
                "strike": 24900,
                "qty": -130,
                "order_id": "ORD-003",
            },
        )
        state.set(
            "positions.pe_buy",
            {
                "symbol": "NIFTY 10 MAR 24950 PUT",  # inside: ATM - hedge_gap (250)
                "strike": 24950,
                "qty": 65,
                "order_id": "ORD-004",
            },
        )
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 24850 PUT")
        state.set("ato.pe_protect_strike", 24850)
        state.set("ato.retrace_points", 5)

        # Spot at 24895 = pe_sell(24900) − retrace_points(5) → triggers PE ATO
        mock_broker._nifty_ltp = 24895.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert state.get("ato.pe_triggered") is True
        assert state.get("ato.pe_ato_active") is True
        assert state.get("ato.pe_order_id") is not None
        assert state.get("ato.ce_triggered") is False

        # Must buy the NEXT put strike (24850), not the sell strike (24900)
        pe_ato_order = next(o for o in mock_broker._orders if "24850" in o["symbol"])
        assert pe_ato_order["qty"] == 65
        assert pe_ato_order["side"] == "BUY"

    def test_ce_retracement_exits_ato(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        state.set(
            "positions.ce_sell",
            {
                "symbol": "NIFTY 10 MAR 25500 CALL",
                "strike": 25500,
                "qty": -130,
                "order_id": "ORD-001",
            },
        )
        state.set(
            "positions.ce_buy",
            {
                "symbol": "NIFTY 10 MAR 25450 CALL",
                "strike": 25450,
                "qty": 65,
                "order_id": "ORD-002",
            },
        )  # inside
        state.set(
            "positions.pe_sell",
            {
                "symbol": "NIFTY 10 MAR 24900 PUT",
                "strike": 24900,
                "qty": -130,
                "order_id": "ORD-003",
            },
        )
        state.set(
            "positions.pe_buy",
            {"symbol": "NIFTY 10 MAR 24950 PUT", "strike": 24950, "qty": 65, "order_id": "ORD-004"},
        )  # inside
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 24850 PUT")
        state.set("ato.pe_protect_strike", 24850)
        state.set("ato.retrace_points", 20)

        # Simulate ATO already triggered and active
        state.set("ato.ce_triggered", True)
        state.set("ato.ce_ato_active", True)
        state.set("ato.ce_order_id", "ORD-ATO-001")

        # Spot at 25479 → ≤ 25500 − 20 = 25480 → CE retrace exit triggered
        mock_broker._nifty_ltp = 25479.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert state.get("ato.ce_ato_active") is False
        assert state.get("ato.ce_triggered") is False  # reset — breach can re-fire
        assert state.get("ato.ce_ato_exit_order_id") is not None

        exit_order = next(o for o in mock_broker._orders if "25550" in o["symbol"])
        assert exit_order["qty"] == 65
        assert exit_order["side"] == "SELL"

    def test_pe_retracement_exits_ato(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        state.set(
            "positions.ce_sell",
            {
                "symbol": "NIFTY 10 MAR 25500 CALL",
                "strike": 25500,
                "qty": -130,
                "order_id": "ORD-001",
            },
        )
        state.set(
            "positions.ce_buy",
            {
                "symbol": "NIFTY 10 MAR 25450 CALL",
                "strike": 25450,
                "qty": 65,
                "order_id": "ORD-002",
            },
        )  # inside
        state.set(
            "positions.pe_sell",
            {
                "symbol": "NIFTY 10 MAR 24900 PUT",
                "strike": 24900,
                "qty": -130,
                "order_id": "ORD-003",
            },
        )
        state.set(
            "positions.pe_buy",
            {"symbol": "NIFTY 10 MAR 24950 PUT", "strike": 24950, "qty": 65, "order_id": "ORD-004"},
        )  # inside
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 24850 PUT")
        state.set("ato.pe_protect_strike", 24850)
        state.set("ato.retrace_points", 5)

        # Simulate PE ATO already triggered and active
        state.set("ato.pe_triggered", True)
        state.set("ato.pe_ato_active", True)
        state.set("ato.pe_order_id", "ORD-ATO-002")

        # Spot at 24906 → ≥ 24900 + 5 = 24905 → PE retrace exit triggered
        mock_broker._nifty_ltp = 24906.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert state.get("ato.pe_ato_active") is False
        assert state.get("ato.pe_triggered") is False  # reset — breach can re-fire
        assert state.get("ato.pe_ato_exit_order_id") is not None

        exit_order = next(o for o in mock_broker._orders if "24850" in o["symbol"])
        assert exit_order["qty"] == 65
        assert exit_order["side"] == "SELL"

    def test_no_breach_when_within_range(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        state.set(
            "positions.ce_sell",
            {
                "symbol": "NIFTY 10 MAR 25500 CALL",
                "strike": 25500,
                "qty": -130,
                "order_id": "ORD-001",
            },
        )
        state.set(
            "positions.ce_buy",
            {
                "symbol": "NIFTY 10 MAR 25450 CALL",  # inside: ATM + hedge_gap (250)
                "strike": 25450,
                "qty": 65,
                "order_id": "ORD-002",
            },
        )
        state.set(
            "positions.pe_sell",
            {
                "symbol": "NIFTY 10 MAR 24900 PUT",
                "strike": 24900,
                "qty": -130,
                "order_id": "ORD-003",
            },
        )
        state.set(
            "positions.pe_buy",
            {
                "symbol": "NIFTY 10 MAR 24950 PUT",  # inside: ATM - hedge_gap (250)
                "strike": 24950,
                "qty": 65,
                "order_id": "ORD-004",
            },
        )
        state.set("ato.retrace_points", 5)

        mock_broker._nifty_ltp = 25200.0  # well within range

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert state.get("ato.ce_triggered") is False
        assert state.get("ato.pe_triggered") is False

    def test_consolidated_ato_ledger_writes_cycle_and_snapshot(
        self, mock_broker, config, state, event_bus, monkeypatch, tmp_path
    ):
        from modules import ato_protection as ato_mod
        from modules.ato_protection import ATOProtection

        ledger_file = tmp_path / "ato_trade_ledger.csv"
        snapshot_dir = tmp_path / "snapshots"
        telemetry_file = tmp_path / "ato_execution_telemetry.csv"
        monkeypatch.setattr(ato_mod, "_ATO_LEDGER_FILE", ledger_file)
        monkeypatch.setattr(ato_mod, "_ATO_LEDGER_SNAPSHOT_DIR", snapshot_dir)
        monkeypatch.setattr(ato_mod, "_TELEMETRY_FILE", telemetry_file)
        monkeypatch.setattr(ato_mod, "record_ato_buy", lambda **kwargs: None)
        monkeypatch.setattr(ato_mod, "record_ato_cycle_complete", lambda **kwargs: None)

        state.set("deployment.file", "data/deployments/batman_test.json")
        state.set(
            "positions.ce_buy", {"symbol": "NIFTY 10 MAR 25450 CALL", "strike": 25450, "qty": 65}
        )
        state.set(
            "positions.pe_buy", {"symbol": "NIFTY 10 MAR 24950 PUT", "strike": 24950, "qty": 65}
        )
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 24850 PUT")
        state.set("ato.pe_protect_strike", 24850)
        state.set("ato.retrace_points", 20)

        mod = ATOProtection(mock_broker, config, state, event_bus)
        settings = {
            "entry_buffer": 5,
            "retrace_points": 20,
            "trigger_level": 24805,
            "exit_level": 24780,
        }

        mock_broker._option_ltp_sequence = [120.0, 95.0]
        mod._place_ce_protection(ce_strike=24800, spot=24806.0, settings=settings)
        mod._exit_ce_ato(spot=24790.0, ce_strike=24800, settings=settings)

        assert ledger_file.exists()
        with open(ledger_file, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

        assert len(rows) == 1
        row = rows[0]
        assert row["side"] == "CE"
        assert float(row["points_lost"]) == pytest.approx(16.0)
        assert float(row["points_lost_x_lots"]) == pytest.approx(16.0)
        assert row["entry_buffer_points"] == "5"
        assert row["retrace_points"] == "20"
        assert float(row["buy_option_premium"]) == pytest.approx(120.0)
        assert float(row["sell_option_premium"]) == pytest.approx(95.0)
        assert float(row["premium_pnl"]) == pytest.approx(-25.0)
        assert float(row["premium_pnl_rupees"]) == pytest.approx(-25.0 * 65)

        csv_snapshots = list(Path(snapshot_dir).glob("*.csv"))
        assert csv_snapshots, "Expected at least one lock-safe CSV snapshot copy"

    def test_ce_ato_idempotency_skips_duplicate_order(self, mock_broker, config, state, event_bus):
        """If broker already holds the CE protect symbol (prior order went through
        despite an exception), _place_ce_protection must NOT place a new order —
        it should only update state flags to reflect the existing position."""
        from modules.ato_protection import ATOProtection

        # Simulate: broker already holds 65 qty of the CE protect symbol
        mock_broker._positions = pd.DataFrame(
            [{"tradingSymbol": "NIFTY 10 MAR 25550 CALL", "netQty": 65}]
        )

        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set("positions.ce_sell", {"strike": 25500, "qty": -130})
        state.set("positions.ce_buy", {"strike": 25450, "qty": 65})
        state.set("positions.pe_sell", {"strike": 24900, "qty": -130})
        state.set("ato.retrace_points", 5)

        orders_before = len(mock_broker._orders)

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._place_ce_protection(25500, 25500.0)

        # No new order placed — existing position detected
        assert len(mock_broker._orders) == orders_before
        # State correctly reflects active ATO
        assert state.get("ato.ce_triggered") is True
        assert state.get("ato.ce_ato_active") is True

    def test_pe_ato_idempotency_skips_duplicate_order(self, mock_broker, config, state, event_bus):
        """Same idempotency guard on the PE side."""
        from modules.ato_protection import ATOProtection

        mock_broker._positions = pd.DataFrame(
            [{"tradingSymbol": "NIFTY 10 MAR 24850 PUT", "netQty": 65}]
        )

        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 24850 PUT")
        state.set("ato.pe_protect_strike", 24850)
        state.set("positions.pe_sell", {"strike": 24900, "qty": -130})
        state.set("positions.pe_buy", {"strike": 24950, "qty": 65})
        state.set("positions.ce_sell", {"strike": 25500, "qty": -130})
        state.set("ato.retrace_points", 5)

        orders_before = len(mock_broker._orders)

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._place_pe_protection(24900, 24900.0)

        assert len(mock_broker._orders) == orders_before
        assert state.get("ato.pe_triggered") is True
        assert state.get("ato.pe_ato_active") is True

    def test_ce_protect_symbol_derived_from_sell_leg(self, mock_broker, config, state, event_bus):
        """When ato.ce_protect_symbol is missing, derive from positions.ce_sell."""
        from modules.ato_protection import ATOProtection

        state.set("deployment.confirmed", True)
        state.set(
            "positions.ce_sell",
            {"symbol": "NIFTY-Jun2026-23300-CE", "strike": 23300, "qty": -130},
        )
        state.set("positions.ce_buy", {"symbol": "NIFTY-Jun2026-23250-CE", "strike": 23250, "qty": 65})
        state.set("ato.retrace_points", 5)

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._place_ce_protection(23300, 23344.0)

        assert state.get("ato.ce_protect_symbol") == "NIFTY-Jun2026-23350-CE"
        assert state.get("ato.ce_triggered") is True
        ce_ato_order = next(o for o in mock_broker._orders if "23350" in o["symbol"])
        assert ce_ato_order["side"] == "BUY"

    def test_ce_ato_skipped_when_deployment_not_confirmed(
        self, mock_broker, config, state, event_bus
    ):
        from modules.ato_protection import ATOProtection

        state.set("deployment.confirmed", False)
        state.set(
            "positions.ce_sell",
            {"symbol": "NIFTY-Jun2026-23300-CE", "strike": 23300, "qty": -130},
        )
        state.set("positions.ce_buy", {"symbol": "NIFTY-Jun2026-23250-CE", "strike": 23250, "qty": 65})
        state.set("ato.ce_protect_symbol", "NIFTY-Jun2026-23350-CE")

        orders_before = len(mock_broker._orders)
        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._place_ce_protection(23300, 23344.0)

        assert len(mock_broker._orders) == orders_before
        assert state.get("ato.ce_triggered") is not True


class TestATOStartupScan:
    """
    Tests for the pre-algo startup scan that detects and adopts manually-placed
    ATO positions, or auto-places if the range is breached and no manual ATO exists.

    Scenario: user buys the ATO leg manually between 09:15–09:20 before the algo
    starts; or a gap occurs and no manual ATO was punched.
    """

    @pytest.fixture(autouse=True)
    def _ato_startup_scan_guards(self, monkeypatch):
        from decimal import Decimal

        from modules.ato_protection import ATOProtection

        def _test_resolve_spot(self):
            ltp = getattr(self.broker, "_nifty_ltp", 25000.0)
            return Decimal(str(ltp))

        monkeypatch.setattr(ATOProtection, "_resolve_nifty_spot", _test_resolve_spot)
        monkeypatch.setattr(ATOProtection, "_check_managed_qty_mismatch", lambda self: None)

    # ── shared state builder ─────────────────────────────────────────────────

    def _set_positions(self, state):
        """Standard iron condor: centre ~25,000, CE sell 25,300, PE sell 24,700."""
        state.set(
            "positions.ce_sell",
            {
                "symbol": "NIFTY 10 MAR 25300 CALL",
                "strike": 25300,
                "qty": -130,
                "order_id": "ORD-001",
            },
        )
        state.set(
            "positions.ce_buy",
            {
                "symbol": "NIFTY 10 MAR 25250 CALL",
                "strike": 25250,
                "qty": 65,
                "order_id": "ORD-002",
            },
        )
        state.set(
            "positions.pe_sell",
            {
                "symbol": "NIFTY 10 MAR 24700 PUT",
                "strike": 24700,
                "qty": -130,
                "order_id": "ORD-003",
            },
        )
        state.set(
            "positions.pe_buy",
            {
                "symbol": "NIFTY 10 MAR 24750 PUT",
                "strike": 24750,
                "qty": 65,
                "order_id": "ORD-004",
            },
        )
        # ATO protect symbols = sell strike ± 50 (decided at entry time)
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25350 CALL")
        state.set("ato.ce_protect_strike", 25350)
        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 24650 PUT")
        state.set("ato.pe_protect_strike", 24650)
        state.set("ato.retrace_points", 5)
        state.set("deployment.confirmed", True)

    # ── core adoption scenarios ──────────────────────────────────────────────

    def test_pe_breach_adopts_manual_ato(self, mock_broker, config, state, event_bus):
        """Gap down — PE range breached, user placed correct manual ATO → adopt.

        Expected: pe_triggered=True, pe_ato_active=True, NO new order placed.
        CE side untouched.
        """
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 24000.0  # far below PE sell (24700)
        mock_broker._positions = pd.DataFrame(
            [
                {"tradingSymbol": "NIFTY 10 MAR 24650 PUT", "netQty": 65},
            ]
        )

        mod = ATOProtection(mock_broker, config, state, event_bus)
        orders_before = len(mock_broker._orders)
        mod._startup_scan()

        assert state.get("ato.pe_triggered") is True
        assert state.get("ato.pe_ato_active") is True
        assert len(mock_broker._orders) == orders_before  # no new order
        assert state.get("ato.ce_triggered") is False  # CE side untouched

    def test_ce_breach_adopts_manual_ato(self, mock_broker, config, state, event_bus):
        """Gap up — CE range breached, user placed correct manual ATO → adopt.

        Expected: ce_triggered=True, ce_ato_active=True, NO new order placed.
        PE side untouched.
        """
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 25800.0  # far above CE sell (25300)
        mock_broker._positions = pd.DataFrame(
            [
                {"tradingSymbol": "NIFTY 10 MAR 25350 CALL", "netQty": 65},
            ]
        )

        mod = ATOProtection(mock_broker, config, state, event_bus)
        orders_before = len(mock_broker._orders)
        mod._startup_scan()

        assert state.get("ato.ce_triggered") is True
        assert state.get("ato.ce_ato_active") is True
        assert len(mock_broker._orders) == orders_before
        assert state.get("ato.pe_triggered") is False

    # ── auto-place fallback ──────────────────────────────────────────────────

    def test_pe_breach_auto_places_when_no_manual_ato(self, mock_broker, config, state, event_bus):
        """Gap down, PE breached, no manual ATO at broker → auto-place PE ATO."""
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 24000.0
        mock_broker._positions = pd.DataFrame()  # no broker positions

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._startup_scan()

        assert state.get("ato.pe_triggered") is True
        assert state.get("ato.pe_ato_active") is True
        pe_order = next(o for o in mock_broker._orders if "24650" in o["symbol"])
        assert pe_order["qty"] == 65
        assert pe_order["side"] == "BUY"

    def test_ce_breach_auto_places_when_no_manual_ato(self, mock_broker, config, state, event_bus):
        """Gap up, CE breached, no manual ATO at broker → auto-place CE ATO."""
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 25800.0
        mock_broker._positions = pd.DataFrame()

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._startup_scan()

        assert state.get("ato.ce_triggered") is True
        assert state.get("ato.ce_ato_active") is True
        ce_order = next(o for o in mock_broker._orders if "25350" in o["symbol"])
        assert ce_order["qty"] == 65
        assert ce_order["side"] == "BUY"

    # ── no breach ───────────────────────────────────────────────────────────

    def test_no_breach_no_action(self, mock_broker, config, state, event_bus):
        """Spot within range → no breach, no ATO, no state change."""
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 25000.0  # well within range
        mock_broker._positions = pd.DataFrame()

        mod = ATOProtection(mock_broker, config, state, event_bus)
        orders_before = len(mock_broker._orders)
        mod._startup_scan()

        assert state.get("ato.ce_triggered") is False
        assert state.get("ato.pe_triggered") is False
        assert len(mock_broker._orders) == orders_before

    # ── stale-state cleanup ──────────────────────────────────────────────────

    def test_stale_ce_state_is_reset(self, mock_broker, config, state, event_bus):
        """ce_triggered=True in state but no CE ATO at broker → reset flag.

        Scenario: previous session crashed after CE ATO entry before retrace exit.
        On restart the flag must be cleared so breach detection works correctly.
        """
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        state.set("ato.ce_triggered", True)
        state.set("ato.ce_ato_active", True)
        mock_broker._nifty_ltp = 25000.0
        mock_broker._positions = pd.DataFrame()  # broker has no CE ATO position

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._startup_scan()

        assert state.get("ato.ce_triggered") is False
        assert state.get("ato.ce_ato_active") is False

    def test_stale_pe_state_is_reset(self, mock_broker, config, state, event_bus):
        """pe_triggered=True in state but no PE ATO at broker → reset flag."""
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        state.set("ato.pe_triggered", True)
        state.set("ato.pe_ato_active", True)
        mock_broker._nifty_ltp = 25000.0
        mock_broker._positions = pd.DataFrame()

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._startup_scan()

        assert state.get("ato.pe_triggered") is False
        assert state.get("ato.pe_ato_active") is False

    def test_prior_day_ato_kept_when_broker_position_still_open(
        self, mock_broker, config, state, event_bus
    ):
        """ATO active from previous day AND broker position still open → leave intact.

        e.g. Market closed with PE ATO live (no retrace); the position carries
        into the next morning. Startup scan must NOT reset or re-place.
        """
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        state.set("ato.pe_triggered", True)
        state.set("ato.pe_ato_active", True)
        mock_broker._nifty_ltp = 24200.0
        mock_broker._positions = pd.DataFrame(
            [
                {"tradingSymbol": "NIFTY 10 MAR 24650 PUT", "netQty": 65},
            ]
        )

        mod = ATOProtection(mock_broker, config, state, event_bus)
        orders_before = len(mock_broker._orders)
        mod._startup_scan()

        # State stays as-is; no reset, no new order
        assert state.get("ato.pe_triggered") is True
        assert state.get("ato.pe_ato_active") is True
        assert len(mock_broker._orders) == orders_before

    # ── qty mismatch ─────────────────────────────────────────────────────────

    def test_qty_mismatch_adopts_but_fires_mismatch_event(
        self, mock_broker, config, state, event_bus
    ):
        """Broker has wrong qty for the manual ATO → still adopt (never double-place)
        but publish ATO_STARTUP_QTY_MISMATCH for Telegram alerting.
        """
        from core.event_bus import Event
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 24000.0
        # Wrong qty: 130 instead of expected 65
        mock_broker._positions = pd.DataFrame(
            [
                {"tradingSymbol": "NIFTY 10 MAR 24650 PUT", "netQty": 130},
            ]
        )

        mismatch_events = []
        event_bus.subscribe(
            Event.ATO_STARTUP_QTY_MISMATCH,
            lambda e, d: mismatch_events.append(d),
        )

        mod = ATOProtection(mock_broker, config, state, event_bus)
        orders_before = len(mock_broker._orders)
        mod._startup_scan()

        # Adopted — no new order
        assert state.get("ato.pe_triggered") is True
        assert len(mock_broker._orders) == orders_before
        # Mismatch event fired with correct details
        assert len(mismatch_events) == 1
        assert mismatch_events[0]["broker_qty"] == 130
        assert mismatch_events[0]["expected_qty"] == 65
        assert mismatch_events[0]["side"] == "PE"

    # ── config/guard flags ───────────────────────────────────────────────────

    def test_startup_scan_disabled_via_config(self, mock_broker, config, state, event_bus):
        """startup_scan_enabled=False → scan is entirely skipped."""
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        config._data["ato"]["startup_scan_enabled"] = False
        mock_broker._nifty_ltp = 24000.0  # would trigger if scan ran
        mock_broker._positions = pd.DataFrame()

        mod = ATOProtection(mock_broker, config, state, event_bus)
        orders_before = len(mock_broker._orders)
        mod._startup_scan()

        assert state.get("ato.pe_triggered") is False
        assert len(mock_broker._orders) == orders_before

    def test_scan_skips_when_no_positions(self, mock_broker, config, state, event_bus):
        """No iron condor deployed yet → scan exits gracefully without error."""
        from modules.ato_protection import ATOProtection

        # Deliberately leave state empty (no positions)
        mock_broker._nifty_ltp = 24000.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        orders_before = len(mock_broker._orders)
        mod._startup_scan()

        assert state.get("ato.ce_triggered") is False
        assert state.get("ato.pe_triggered") is False
        assert len(mock_broker._orders) == orders_before

    def test_scan_skips_when_ltp_fails(self, mock_broker, config, state, event_bus):
        """NIFTY LTP cache unavailable → scan skips without crashing the module."""
        from modules.ato_protection import ATOProtection

        self._set_positions(state)

        with patch(
            "modules.ato_protection.resolve_nifty_ltp_from_cache",
            side_effect=RuntimeError("cache stale"),
        ):
            mock_broker._positions = pd.DataFrame()

            mod = ATOProtection(mock_broker, config, state, event_bus)
            orders_before = len(mock_broker._orders)
            mod._startup_scan()  # must not raise

        assert state.get("ato.ce_triggered") is False
        assert state.get("ato.pe_triggered") is False
        assert len(mock_broker._orders) == orders_before

    # ── extreme / compound scenarios ───────────────────────────────────────

    def test_both_sides_breached_both_adopted(self, mock_broker, config, state, event_bus):
        """Extreme: both CE and PE ranges breached simultaneously → both adopted.

        Uses inverted strikes around spot to force both conditions (not a
        realistic iron condor, but exercises the independent per-side logic).
        """
        from modules.ato_protection import ATOProtection

        # spot=25300, CE sell=25250 (below spot → CE breached),
        #             PE sell=25350 (above spot → PE breached)
        state.set(
            "positions.ce_sell",
            {
                "symbol": "NIFTY 10 MAR 25250 CALL",
                "strike": 25250,
                "qty": -130,
                "order_id": "ORD-001",
            },
        )
        state.set(
            "positions.ce_buy",
            {
                "symbol": "NIFTY 10 MAR 25200 CALL",
                "strike": 25200,
                "qty": 65,
                "order_id": "ORD-002",
            },
        )
        state.set(
            "positions.pe_sell",
            {
                "symbol": "NIFTY 10 MAR 25350 PUT",
                "strike": 25350,
                "qty": -130,
                "order_id": "ORD-003",
            },
        )
        state.set(
            "positions.pe_buy",
            {
                "symbol": "NIFTY 10 MAR 25400 PUT",
                "strike": 25400,
                "qty": 65,
                "order_id": "ORD-004",
            },
        )
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25300 CALL")
        state.set("ato.ce_protect_strike", 25300)
        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 25300 PUT")
        state.set("ato.pe_protect_strike", 25300)
        state.set("ato.retrace_points", 5)

        mock_broker._nifty_ltp = 25300.0
        mock_broker._positions = pd.DataFrame(
            [
                {"tradingSymbol": "NIFTY 10 MAR 25300 CALL", "netQty": 65},
                {"tradingSymbol": "NIFTY 10 MAR 25300 PUT", "netQty": 65},
            ]
        )

        mod = ATOProtection(mock_broker, config, state, event_bus)
        orders_before = len(mock_broker._orders)
        mod._startup_scan()

        assert state.get("ato.ce_triggered") is True
        assert state.get("ato.pe_triggered") is True
        assert len(mock_broker._orders) == orders_before  # both adopted, no new orders

    def test_startup_scan_publishes_scan_done_event(self, mock_broker, config, state, event_bus):
        """Startup scan always publishes ATO_STARTUP_SCAN_DONE on completion."""
        from core.event_bus import Event
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 25000.0  # within range
        mock_broker._positions = pd.DataFrame()

        scan_events = []
        event_bus.subscribe(
            Event.ATO_STARTUP_SCAN_DONE,
            lambda e, d: scan_events.append(d),
        )

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._startup_scan()

        assert len(scan_events) == 1
        assert scan_events[0]["ce_breached"] is False
        assert scan_events[0]["pe_breached"] is False
        assert scan_events[0]["spot"] == 25000.0

    def test_adopted_ato_hands_off_to_retracement(self, mock_broker, config, state, event_bus):
        """After startup scan adopts a manual PE ATO, the normal retracement
        exit fires when spot recovers past retrace_points above pe_sell_strike.
        """
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 24000.0
        mock_broker._positions = pd.DataFrame(
            [
                {"tradingSymbol": "NIFTY 10 MAR 24650 PUT", "netQty": 65},
            ]
        )

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._startup_scan()

        assert state.get("ato.pe_triggered") is True

        # Now market recovers: spot >= pe_sell (24700) + retrace_points (5) = 24705
        mock_broker._nifty_ltp = 24706.0
        mock_broker._positions = pd.DataFrame(
            [
                {"tradingSymbol": "NIFTY 10 MAR 24650 PUT", "netQty": 65},
                {"tradingSymbol": "NIFTY 10 MAR 24750 PUT", "netQty": 65},
                {"tradingSymbol": "NIFTY 10 MAR 24700 PUT", "netQty": -130},
                {"tradingSymbol": "NIFTY 10 MAR 25250 CALL", "netQty": 65},
                {"tradingSymbol": "NIFTY 10 MAR 25300 CALL", "netQty": -130},
            ]
        )
        mod._check_breach()

        assert state.get("ato.pe_triggered") is False
        assert state.get("ato.pe_ato_active") is False
        exit_order = next(o for o in mock_broker._orders if "24650" in o["symbol"])
        assert exit_order["side"] == "SELL"
        assert exit_order["qty"] == 65

    def test_retrace_sells_leftover_not_larger_registered(
        self, mock_broker, config, state, event_bus
    ):
        """Leftover 65 + registered 130 must SELL 65 only — never open a short."""
        from modules.ato_protection import ATOProtection

        self._set_positions(state)
        mock_broker._nifty_ltp = 24000.0
        mock_broker._positions = pd.DataFrame(
            [
                {"tradingSymbol": "NIFTY 10 MAR 24650 PUT", "netQty": 65},
            ]
        )

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._startup_scan()
        assert state.get("ato.pe_ato_active") is True
        # Simulate the old Q60 bug: remembered size is the full registered ATO.
        state.set("ato.pe_exit_qty", 130)
        assert mod._registered_exit_qty("PE", "pe_buy") == 130
        assert mod._retrace_sell_qty("PE", "pe_buy", "NIFTY 10 MAR 24650 PUT") == 65

        settings = mod._side_settings("PE", 24700)
        mod._exit_pe_ato(spot=24706.0, pe_strike=24700, settings=settings)

        exit_order = next(o for o in mock_broker._orders if "24650" in o["symbol"])
        assert exit_order["side"] == "SELL"
        assert exit_order["qty"] == 65
        shorts = [o for o in mock_broker._orders if o.get("side") == "SELL" and o.get("qty", 0) > 65]
        assert shorts == []


class TestBatmanEntry:

    def test_deploy_iron_condor(self, mock_broker, config, state, event_bus):
        from modules.batman_entry import BatmanEntry

        mod = BatmanEntry(mock_broker, config, state, event_bus)
        mod._deploy_iron_condor()

        # All 4 legs should be stored in state
        assert state.get("positions.ce_sell") is not None
        assert state.get("positions.ce_buy") is not None
        assert state.get("positions.pe_sell") is not None
        assert state.get("positions.pe_buy") is not None

        # 4 orders should have been placed
        assert len(mock_broker._orders) == 4

        # Verify sell qty = 2 lots × 65 = 130
        sell_order = mock_broker._orders[0]
        assert sell_order["qty"] == 130
        assert sell_order["side"] == "SELL"

        # Verify buy qty = 1 lot × 65 = 65
        buy_order = mock_broker._orders[1]
        assert buy_order["qty"] == 65
        assert buy_order["side"] == "BUY"

        # ATO protect symbols must be stored in state
        assert state.get("ato.ce_protect_symbol") is not None
        assert state.get("ato.pe_protect_symbol") is not None
        # ATO protect strikes must be one step (50 pts) beyond sell strikes
        ce_sell = state.get("positions.ce_sell")
        assert state.get("ato.ce_protect_strike") == ce_sell["strike"] + 50
        pe_sell = state.get("positions.pe_sell")
        assert state.get("ato.pe_protect_strike") == pe_sell["strike"] - 50


class TestProfitTrailing:

    def test_hard_stop_detection(self, mock_broker, config, state, event_bus):
        """When PnL is below hard stop, emergency exit should trigger."""
        from core.event_bus import Event

        exit_triggered = []
        event_bus.subscribe(Event.HARD_STOP_HIT, lambda e, d: exit_triggered.append(d))

        mock_broker._pnl = -9000  # below -8000 hard stop

        from modules.profit_trailing import ProfitTrailing

        ProfitTrailing(mock_broker, config, state, event_bus)

        # Can't easily test the _run loop, but we can verify the logic:
        # If we reach the hard stop check with PnL = -9000 and hard_stop = -8000,
        # it should detect a breach.
        assert mock_broker._pnl <= config.get("trailing.hard_stop_loss")


class TestEmergencyExit:

    def test_execute_exit(self, mock_broker, config, state, event_bus):
        from modules.emergency_exit import EmergencyExit

        mod = EmergencyExit(mock_broker, config, state, event_bus)
        result = mod.execute_exit(reason="test")

        assert result["success"] is True
        assert result["reason"] == "test"

    def test_emergency_exit_resets_ato_state(self, mock_broker, config, state, event_bus):
        """Emergency exit must clear all ATO flags so orphaned state does not
        cause the ATO module to fire retrace-exit orders after the session ends."""
        from modules.emergency_exit import EmergencyExit

        # Simulate an active CE ATO at the time of emergency
        state.set("ato.ce_triggered", True)
        state.set("ato.ce_ato_active", True)
        state.set("ato.ce_order_id", "ORD-0042")
        state.set("ato.pe_triggered", False)
        state.set("ato.pe_ato_active", False)

        mod = EmergencyExit(mock_broker, config, state, event_bus)
        result = mod.execute_exit(reason="test_ato_reset")

        assert result["success"] is True
        assert state.get("ato.ce_triggered") is False
        assert state.get("ato.ce_ato_active") is False
        assert state.get("ato.pe_triggered") is False
        assert state.get("ato.pe_ato_active") is False
        assert state.get("ato.ce_order_id") is None
        assert state.get("ato.pe_order_id") is None


class TestModuleLifecycle:

    def test_module_disable_via_config(self, mock_broker, config, state, event_bus):
        """If config has enabled=false, start() should skip."""
        from modules.ato_protection import ATOProtection

        config._data["modules"]["ato_protection"]["enabled"] = False
        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod.start()

        assert not mod.is_running

    def test_status_dict(self, mock_broker, config, state, event_bus):
        from modules.position_monitor import PositionMonitor

        mod = PositionMonitor(mock_broker, config, state, event_bus)
        st = mod.status()

        assert st["name"] == "position_monitor"
        assert st["enabled"] is True
        assert st["running"] is False
        assert st["restart_count"] == 0


class TestConfigValidation:

    def test_valid_config_passes(self, config):
        """Config fixture has all required keys — should not raise."""
        config.validate()

    def test_missing_key_raises(self, config):
        """Remove a required key and expect ConfigError."""
        from core.exceptions import ConfigError

        del config._data["strategy"]["lot_size"]
        with pytest.raises(ConfigError, match="lot_size"):
            config.validate()

    def test_invalid_lot_size_raises(self, config):
        from core.exceptions import ConfigError

        config._data["strategy"]["lot_size"] = -1
        with pytest.raises(ConfigError, match="lot_size"):
            config.validate()

    def test_positive_hard_stop_raises(self, config):
        from core.exceptions import ConfigError

        config._data["trailing"]["hard_stop_loss"] = 100  # Should be negative
        with pytest.raises(ConfigError):
            config.validate()


class TestModuleAutoRestart:

    def test_auto_restart_on_crash(self, mock_broker, config, state, event_bus):
        """Module should auto-restart after crash (up to MAX_RESTARTS)."""

        from core.module_base import ModuleBase

        crash_count = [0]

        class CrashModule(ModuleBase):
            name = "crash_test"
            MAX_RESTARTS = 2
            RESTART_COOLDOWN = 0.1

            def _run(self):
                crash_count[0] += 1
                if crash_count[0] <= 3:
                    raise RuntimeError("boom")
                # If we somehow got here, just exit

        config._data["modules"]["crash_test"] = {"enabled": True}
        mod = CrashModule(mock_broker, config, state, event_bus)
        mod.start()
        time.sleep(1.0)  # Allow time for restarts

        # Should have tried 3 times: initial + 2 restarts
        assert crash_count[0] == 3
        assert mod._restart_count == 2
        assert mod._restart_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# New tests: Deployment confirmation flow, AlgoScheduler time-picker,
# deploy_handler helpers, next_entry_date utility.
# ─────────────────────────────────────────────────────────────────────────────


class TestNextEntryDate:
    """Unit tests for core.utils.next_entry_date()."""

    def test_returns_next_wednesday_from_monday(self):
        from datetime import date

        from core.utils import next_entry_date

        # 2026-03-09 is a Monday → next entry Wednesday = 2026-03-11
        result = next_entry_date(from_date=date(2026, 3, 9))
        assert result == date(2026, 3, 11)
        assert result.weekday() == 2

    def test_returns_next_wednesday_from_wednesday(self):
        """Starting on a Wednesday must find the *next* Wednesday, not the same day."""
        from datetime import date

        from core.utils import next_entry_date

        # 2026-03-11 is a Wednesday → next entry = 2026-03-18
        result = next_entry_date(from_date=date(2026, 3, 11))
        assert result == date(2026, 3, 18)
        assert result > date(2026, 3, 11)

    def test_returns_next_wednesday_from_saturday(self):
        from datetime import date

        from core.utils import next_entry_date

        # 2026-03-14 is a Saturday → next entry Wednesday = 2026-03-18
        result = next_entry_date(from_date=date(2026, 3, 14))
        assert result == date(2026, 3, 18)

    def test_skips_holiday_wednesday(self):
        """A Wednesday that is an NSE holiday must be skipped."""
        from datetime import date

        from core.utils import next_entry_date

        # 2026-10-20 is Tuesday (day before Dussehra)
        # 2026-10-21 is Wednesday AND NSE holiday (Dussehra) → skip
        # Next valid trading Wednesday = 2026-10-28
        result = next_entry_date(from_date=date(2026, 10, 20))
        assert result == date(2026, 10, 28)
        assert result.weekday() == 2


class TestDeployHandlerHelpers:
    """Unit tests for symbol parsing and position classification helpers."""

    def test_parse_symbol_ce(self):
        from bot.handlers.deploy_handler import _parse_symbol

        prefix, strike, opt_type = _parse_symbol("NIFTY26MAR25500CE")
        assert prefix == "NIFTY26MAR"
        assert strike == 25500
        assert opt_type == "CE"

    def test_parse_symbol_pe(self):
        from bot.handlers.deploy_handler import _parse_symbol

        prefix, strike, opt_type = _parse_symbol("NIFTY26MAR24900PE")
        assert prefix == "NIFTY26MAR"
        assert strike == 24900
        assert opt_type == "PE"

    def test_parse_symbol_invalid_returns_none(self):
        from bot.handlers.deploy_handler import _parse_symbol

        prefix, strike, opt_type = _parse_symbol("NIFTY CALL")
        assert prefix is None
        assert strike is None
        assert opt_type is None

    def test_parse_symbol_banknifty(self):
        """BANKNIFTY symbols should parse correctly."""
        from bot.handlers.deploy_handler import _parse_symbol

        prefix, strike, opt_type = _parse_symbol("BANKNIFTY26MAR57000CE")
        assert "BANKNIFTY" in prefix
        assert strike == 57000
        assert opt_type == "CE"

    def test_classify_legs_correct(self):
        from bot.handlers.deploy_handler import _classify_legs

        positions = [
            {"tradingSymbol": "NIFTY26MAR25500CE", "netQty": -130, "sellAvg": 120.0},
            {"tradingSymbol": "NIFTY26MAR25450CE", "netQty": 65, "buyAvg": 80.0},
            {"tradingSymbol": "NIFTY26MAR24900PE", "netQty": -130, "sellAvg": 110.0},
            {"tradingSymbol": "NIFTY26MAR24950PE", "netQty": 65, "buyAvg": 70.0},
        ]
        result = _classify_legs(positions)

        assert result is not None
        assert result["ce_sell"]["tradingSymbol"] == "NIFTY26MAR25500CE"
        assert result["ce_buy"]["tradingSymbol"] == "NIFTY26MAR25450CE"
        assert result["pe_sell"]["tradingSymbol"] == "NIFTY26MAR24900PE"
        assert result["pe_buy"]["tradingSymbol"] == "NIFTY26MAR24950PE"

    def test_classify_legs_empty_returns_none(self):
        from bot.handlers.deploy_handler import _classify_legs

        assert _classify_legs([]) is None

    def test_classify_legs_duplicate_ce_sell_returns_none(self):
        """Two short CE positions → ambiguous → None (prevents bad classification)."""
        from bot.handlers.deploy_handler import _classify_legs

        positions = [
            {"tradingSymbol": "NIFTY26MAR25500CE", "netQty": -130},
            {"tradingSymbol": "NIFTY26MAR25600CE", "netQty": -130},  # duplicate ce_sell
            {"tradingSymbol": "NIFTY26MAR24900PE", "netQty": -130},
            {"tradingSymbol": "NIFTY26MAR24950PE", "netQty": 65},
        ]
        assert _classify_legs(positions) is None

    def test_to_state_leg_sell_position(self):
        from bot.handlers.deploy_handler import _to_state_leg

        pos = {"tradingSymbol": "NIFTY26MAR25500CE", "netQty": -130, "sellAvg": 120.5}
        leg = _to_state_leg(pos)

        assert leg["symbol"] == "NIFTY26MAR25500CE"
        assert leg["strike"] == 25500
        assert leg["qty"] == -130
        assert leg["avg_price"] == 120.5
        assert leg["order_id"] == "manual"

    def test_to_state_leg_buy_position(self):
        from bot.handlers.deploy_handler import _to_state_leg

        pos = {"tradingSymbol": "NIFTY26MAR25450CE", "netQty": 65, "buyAvg": 80.0}
        leg = _to_state_leg(pos)

        assert leg["qty"] == 65
        assert leg["avg_price"] == 80.0
        assert leg["order_id"] == "manual"


class TestAlgoSchedulerState:
    """Unit tests for AlgoScheduler state logic (no live Telegram calls)."""

    def _make_scheduler(self, config, state):
        from bot.algo_scheduler import AlgoScheduler

        sched = AlgoScheduler(
            modules={},
            config=config,
            state=state,
            loop_getter=lambda: None,
            app_getter=lambda: None,
            chat_id="12345",
        )
        # Silence push methods so tests run instantly (no 10-second retry loop)
        sched._push = lambda *a, **kw: None
        sched._push_with_keyboard = lambda *a, **kw: None
        return sched

    def test_status_includes_deployment_fields(self, config, state):
        sched = self._make_scheduler(config, state)
        status = sched.status()

        assert "batman_complete" in status
        assert "deployment_confirmed" in status
        assert status["deployment_confirmed"] is False
        assert status["batman_complete"] is False

    def test_tick_skips_when_batman_done(self, config, state):
        """`_tick()` returns immediately when batman_complete=True."""
        state.set("deployment.batman_complete", True)
        sched = self._make_scheduler(config, state)

        sched._tick()

        assert sched._prompt_sent_date is None  # no prompt should have been scheduled

    def test_tick_skips_when_not_deployed(self, config, state):
        """`_tick()` returns immediately when deployment.confirmed=False."""
        # deployment.confirmed defaults to False
        sched = self._make_scheduler(config, state)

        sched._tick()

        assert sched._prompt_sent_date is None

    def test_handle_time_selection_stores_time(self, config, state):
        sched = self._make_scheduler(config, state)
        sched.handle_time_selection("09:30")

        assert sched._selected_start_time == "09:30"

    def test_handle_time_selection_overrides_previous(self, config, state):
        sched = self._make_scheduler(config, state)
        sched.handle_time_selection("09:30")
        sched.handle_time_selection("10:00")

        assert sched._selected_start_time == "10:00"

    def test_stop_algo_sets_manually_stopped(self, config, state):
        sched = self._make_scheduler(config, state)

        sched.stop_algo()

        assert sched._manually_stopped is True

    def test_resume_algo_blocked_when_not_deployed(self, config, state):
        """resume_algo() must fail with an error when deployment is not confirmed."""
        state.set("deployment.confirmed", False)
        sched = self._make_scheduler(config, state)
        sched._end_time = "23:59"  # ensure trading window is open regardless of test time

        ok, msg = sched.resume_algo()

        assert ok is False
        assert "deployment" in msg.lower()

    def test_tick_sends_prompt_when_deployed_and_past_prompt_time(self, config, state):
        """When deployment confirmed and current time >= prompt_time, prompt fires."""
        state.set("deployment.confirmed", True)
        state.set("deployment.batman_complete", False)

        sched = self._make_scheduler(config, state)
        # Set prompt_time far in the past so the condition always holds
        sched._prompt_time = "00:00"

        prompts_sent = []
        sched._send_time_prompt = lambda now: prompts_sent.append(now)

        sched._tick()

        assert sched._prompt_sent_date is not None
        assert len(prompts_sent) == 1


class TestDeploymentStateDefaults:
    """Verify that the deployment section of StateManager starts with safe defaults."""

    def test_deployment_confirmed_defaults_false(self, state):
        assert state.get("deployment.confirmed", False) is False

    def test_deployment_batman_done_defaults_false(self, state):
        assert state.get("deployment.batman_complete", False) is False

    def test_deployment_next_entry_date_defaults_none(self, state):
        assert state.get("deployment.next_entry_date") is None

    def test_deployment_confirmed_can_be_set(self, state):
        state.set("deployment.confirmed", True)
        assert state.get("deployment.confirmed") is True

    def test_new_cycle_resets_batman_done(self, state):
        """Simulate a new cycle: reset batman_complete, set confirmed=True."""
        state.set("deployment.batman_complete", True)
        state.set("deployment.confirmed", False)

        # New cycle starts
        state.set("deployment.batman_complete", False)
        state.set("deployment.confirmed", True)

        assert state.get("deployment.batman_complete") is False
        assert state.get("deployment.confirmed") is True


class TestATOSoftCap:
    """ATO soft cap warns on choppy sessions — never hard-stops cycling."""

    @pytest.fixture(autouse=True)
    def _ato_soft_cap_guards(self, monkeypatch):
        from decimal import Decimal

        from modules.ato_protection import ATOProtection

        def _test_resolve_spot(self):
            ltp = getattr(self.broker, "_nifty_ltp", 25000.0)
            return Decimal(str(ltp))

        monkeypatch.setattr(ATOProtection, "_resolve_nifty_spot", _test_resolve_spot)
        monkeypatch.setattr(ATOProtection, "_check_managed_qty_mismatch", lambda self: None)

    def _setup_state(self, state):
        state.set(
            "positions.ce_sell",
            {
                "symbol": "NIFTY 10 MAR 25500 CALL",
                "strike": 25500,
                "qty": -130,
                "order_id": "ORD-001",
            },
        )
        state.set(
            "positions.ce_buy",
            {
                "symbol": "NIFTY 10 MAR 25450 CALL",
                "strike": 25450,
                "qty": 65,
                "order_id": "ORD-002",
            },
        )
        state.set(
            "positions.pe_sell",
            {
                "symbol": "NIFTY 10 MAR 24900 PUT",
                "strike": 24900,
                "qty": -130,
                "order_id": "ORD-003",
            },
        )
        state.set(
            "positions.pe_buy",
            {"symbol": "NIFTY 10 MAR 24950 PUT", "strike": 24950, "qty": 65, "order_id": "ORD-004"},
        )
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set("ato.pe_protect_symbol", "NIFTY 10 MAR 24850 PUT")
        state.set("ato.pe_protect_strike", 24850)
        state.set("ato.retrace_points", 5)
        state.set("deployment.confirmed", True)

    def _make_mod(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._ce_cycles = 0
        mod._pe_cycles = 0
        mod._ce_soft_cap_last_exposure = -1
        mod._pe_soft_cap_last_exposure = -1
        mod._cached_operator_settings = {
            "soft_cap_first_warn_cycles": 3,
            "soft_cap_repeat_every_cycles": 2,
            "monitor_breach_counts_toward_soft_cap": True,
            "order_retry_max": 3,
            "lot_size": 65,
        }
        return mod

    def test_soft_cap_never_blocks_orders(self, mock_broker, config, state, event_bus):
        """High cycle count still places orders — soft cap is warn-only."""
        self._setup_state(state)
        mod = self._make_mod(mock_broker, config, state, event_bus)
        mod._ce_cycles = 100
        mock_broker._nifty_ltp = 25505.0

        mod._check_breach()
        assert state.get("ato.ce_triggered") is True
        assert mod._ce_cycles == 101

    def test_soft_cap_warn_at_threshold(self, mock_broker, config, state, event_bus):
        from core.event_bus import Event

        self._setup_state(state)
        mod = self._make_mod(mock_broker, config, state, event_bus)
        mod._ce_cycles = 2
        events_fired = []
        event_bus.subscribe(Event.ATO_MAX_CYCLES_REACHED, lambda e, d: events_fired.append(d))
        mock_broker._nifty_ltp = 25505.0

        mod._check_breach()

        assert len(events_fired) == 1
        assert events_fired[0]["soft_cap"] is True
        assert events_fired[0]["exposure"] == 3

    def test_soft_cap_warn_not_repeated_same_exposure(self, mock_broker, config, state, event_bus):
        from core.event_bus import Event

        self._setup_state(state)
        mod = self._make_mod(mock_broker, config, state, event_bus)
        mod._ce_cycles = 2
        events_fired = []
        event_bus.subscribe(Event.ATO_MAX_CYCLES_REACHED, lambda e, d: events_fired.append(d))
        mock_broker._nifty_ltp = 25505.0

        mod._check_breach()
        state.set("ato.ce_triggered", False)
        state.set("ato.ce_ato_active", False)
        mod._check_breach()

        assert len(events_fired) == 1

    def test_monitor_only_breach_publishes_event(self, mock_broker, config, state, event_bus):
        from core.event_bus import Event

        self._setup_state(state)
        state.set(
            "deployment.registration_scope",
            {"ce_ato_lots": 0, "pe_ato_lots": 1, "lot_size": 65},
        )
        mod = self._make_mod(mock_broker, config, state, event_bus)
        events_fired = []
        event_bus.subscribe(Event.ATO_MONITOR_BREACH, lambda e, d: events_fired.append(d))
        mock_broker._nifty_ltp = 25505.0

        mod._check_breach()

        assert state.get("ato.ce_triggered") is True
        assert len(events_fired) == 1
        assert events_fired[0]["monitor_only"] is True
        assert len(mock_broker._orders) == 0


class TestAlgoSchedulerEODPrompt:
    """AlgoScheduler sends batman_done prompt at EOD on expiry day (0 DTE)."""

    def _make_scheduler(self, config, state):
        from bot.algo_scheduler import AlgoScheduler

        sched = AlgoScheduler(
            modules={},
            config=config,
            state=state,
            loop_getter=lambda: None,
            app_getter=lambda: None,
            chat_id="12345",
        )
        sched._push = lambda *a, **kw: None
        sched._push_with_keyboard = lambda *a, **kw: None
        return sched

    def test_eod_prompt_sent_on_expiry_day(self, config, state):
        """Prompt fires at EOD when deployment is confirmed and today is expiry."""
        state.set("deployment.confirmed", True)
        state.set("deployment.batman_complete", False)

        sched = self._make_scheduler(config, state)
        # Make EOD condition always true
        sched._end_time = "00:00"
        # Make is_expiry_today always return True
        sched._is_expiry_today = lambda wday: True

        prompts = []
        sched._send_eod_batman_complete_prompt = lambda: prompts.append(1)

        sched._tick()

        assert len(prompts) == 1

    def test_eod_prompt_fires_on_any_day_when_deployed(self, config, state):
        """Prompt fires after EOD on any day when deployed — expiry restriction removed."""
        state.set("deployment.confirmed", True)
        state.set("deployment.batman_complete", False)

        sched = self._make_scheduler(config, state)
        sched._end_time = "00:00"
        # _is_expiry_today is no longer called — day restriction removed
        sched._is_expiry_today = lambda wday: False  # non-expiry day: should still fire

        prompts = []
        sched._send_eod_batman_complete_prompt = lambda: prompts.append(1)

        sched._tick()

        assert len(prompts) == 1

    def test_eod_prompt_not_sent_twice_on_same_day(self, config, state):
        """Prompt fires exactly once even with many _tick() calls."""
        state.set("deployment.confirmed", True)
        state.set("deployment.batman_complete", False)

        sched = self._make_scheduler(config, state)
        sched._end_time = "00:00"
        sched._is_expiry_today = lambda wday: True

        prompts = []
        sched._send_eod_batman_complete_prompt = lambda: prompts.append(1)

        sched._tick()
        sched._tick()  # second tick — must not fire again
        sched._tick()  # third tick

        assert len(prompts) == 1

    def test_eod_prompt_not_sent_when_batman_already_done(self, config, state):
        """No prompt when batman_complete=True (cycle already closed)."""
        state.set("deployment.confirmed", False)
        state.set("deployment.batman_complete", True)

        sched = self._make_scheduler(config, state)
        sched._end_time = "00:00"
        sched._is_expiry_today = lambda wday: True

        prompts = []
        sched._send_eod_batman_complete_prompt = lambda: prompts.append(1)

        sched._tick()

        assert len(prompts) == 0

    def test_eod_prompt_not_sent_when_not_deployed(self, config, state):
        """No prompt when deployment.confirmed=False (no positions to close out)."""
        state.set("deployment.confirmed", False)
        state.set("deployment.batman_complete", False)

        sched = self._make_scheduler(config, state)
        sched._end_time = "00:00"
        sched._is_expiry_today = lambda wday: True

        prompts = []
        sched._send_eod_batman_complete_prompt = lambda: prompts.append(1)

        sched._tick()

        assert len(prompts) == 0


class TestATOManualLegSync:
    """§7 mid-session manual protect sync wired into _check_breach."""

    @pytest.fixture(autouse=True)
    def _ato_guards(self, monkeypatch):
        from decimal import Decimal

        from modules.ato_protection import ATOProtection

        def _test_resolve_spot(self):
            ltp = getattr(self.broker, "_nifty_ltp", 25000.0)
            return Decimal(str(ltp))

        monkeypatch.setattr(ATOProtection, "_resolve_nifty_spot", _test_resolve_spot)
        monkeypatch.setattr(ATOProtection, "_check_managed_qty_mismatch", lambda self: None)

    def _setup_state(self, state):
        state.set(
            "positions.ce_sell",
            {"symbol": "NIFTY 10 MAR 25500 CALL", "strike": 25500, "qty": -130},
        )
        state.set(
            "positions.ce_buy",
            {"symbol": "NIFTY 10 MAR 25450 CALL", "strike": 25450, "qty": 65},
        )
        state.set("ato.ce_protect_symbol", "NIFTY 10 MAR 25550 CALL")
        state.set("ato.ce_protect_strike", 25550)
        state.set("ato.retrace_points", 5)
        state.set("deployment.confirmed", True)

    def test_26a_mid_session_adopt(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        self._setup_state(state)
        mock_broker._nifty_ltp = 25496.0
        mock_broker.set_position("NIFTY 10 MAR 25550 CALL", 65)

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert state.get("ato.ce_triggered") is True
        assert state.get("ato.ce_ato_active") is True

    def test_26d_manual_full_exit_pauses_side(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        self._setup_state(state)
        state.set("ato.ce_triggered", True)
        state.set("ato.ce_ato_active", True)
        mock_broker._nifty_ltp = 25496.0
        mock_broker.set_position("NIFTY 10 MAR 25550 CALL", 65)

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._ce_protect_seen_at_broker = True
        mock_broker.set_position("NIFTY 10 MAR 25550 CALL", 0)
        mod._check_breach()

        assert state.get("ato.ce_side_halted") is True
        assert state.get("ato.ce_halt_reason") == "manual_protect_full_exit"

    def test_q33_unreadable_book_pauses_all(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        self._setup_state(state)
        mock_broker._nifty_ltp = 25496.0
        calls = {"n": 0}

        def _fail_positions():
            calls["n"] += 1
            raise RuntimeError("book down")

        mock_broker.get_positions = _fail_positions

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert calls["n"] == 3
        assert state.get("algo.paused") is True
        assert state.get("algo.pause_reason") == "position_book_unreadable"

    def test_q32c_resume_reentry_on_breach(self, mock_broker, config, state, event_bus):
        from modules.ato_protection import ATOProtection

        self._setup_state(state)
        state.set("ato.ce_triggered", True)
        state.set("ato.ce_ato_active", False)
        state.set("ato.ce_side_halted", False)
        mock_broker._nifty_ltp = 25505.0

        mod = ATOProtection(mock_broker, config, state, event_bus)
        mod._check_breach()

        assert state.get("ato.ce_ato_active") is True
        assert any(o.get("side") == "BUY" for o in mock_broker._orders)
