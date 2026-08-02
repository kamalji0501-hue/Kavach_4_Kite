"""
Batman v3 — Test fixtures.

Provides a MockBroker that simulates Tradehull responses
without needing real API credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

# Ensure batman_v3 root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Telegram stub ─────────────────────────────────────────────────────────────
# python-telegram-bot is not installed in the test environment.
# Provide lightweight mocks so bot modules can be imported without errors.
# Uses setdefault so a real installation is preferred if present.
for _mod in (
    "telegram",
    "telegram.ext",
    "telegram.error",
    "telegram.constants",
    "telegram.helpers",
):
    sys.modules.setdefault(_mod, MagicMock())


def _escape_markdown_test(text: str, version: int = 2, entity_type: str | None = None) -> str:
    """Minimal MarkdownV2 escape for tests (mirrors python-telegram-bot behaviour)."""
    del version
    special = r"_*[]()~`>#+-=|{}.!"
    if entity_type == "code":
        special = r"`\\"
    out = str(text)
    for ch in special:
        out = out.replace(ch, f"\\{ch}")
    return out


_tg_helpers = sys.modules["telegram.helpers"]
_tg_helpers.escape_markdown = _escape_markdown_test

_tg_error = sys.modules["telegram.error"]


class _TelegramBadRequest(Exception):
    """Stand-in for telegram.error.BadRequest in tests."""


_tg_error.BadRequest = _TelegramBadRequest


# ── Mock Broker ──────────────────────────────────────────────


class MockBroker:
    """Drop-in replacement for BatmanBroker during tests."""

    def __init__(self):
        self._nifty_ltp = 25200.0
        self._pnl = 0.0
        self._balance = 500000.0
        self._orders = []
        self._positions = pd.DataFrame()

    # Market data
    def get_ltp(self, names):
        return {n: self._nifty_ltp for n in names}

    def get_nifty_ltp(self):
        return self._nifty_ltp

    def atm_strike(self, underlying="NIFTY", expiry=0):
        s = int(round(self._nifty_ltp / 50) * 50)
        return f"NIFTY 10 MAR {s} CALL", f"NIFTY 10 MAR {s} PUT", s

    def otm_strike(self, underlying="NIFTY", expiry=0, otm_count=6):
        s = int(round(self._nifty_ltp / 50) * 50)
        ce_strike = s + otm_count * 50
        pe_strike = s - otm_count * 50
        return (
            f"NIFTY 10 MAR {ce_strike} CALL",
            f"NIFTY 10 MAR {pe_strike} PUT",
            ce_strike,
            pe_strike,
        )

    # Orders
    def place_order(self, symbol, **kw):
        oid = f"ORD-{len(self._orders)+1:04d}"
        self._orders.append({"order_id": oid, "symbol": symbol, **kw})
        return oid

    def place_market_order(self, symbol, qty, side, trade_type="MARGIN", exchange="NFO"):
        oid = self.place_order(symbol, qty=qty, side=side, trade_type=trade_type)
        signed = int(qty) if str(side).upper() == "BUY" else -int(qty)
        row = {
            "tradingSymbol": symbol,
            "netQty": signed,
            "buyQty": int(qty) if signed > 0 else 0,
            "sellQty": int(qty) if signed < 0 else 0,
        }
        if self._positions.empty:
            self._positions = pd.DataFrame([row])
        else:
            mask = self._positions["tradingSymbol"] == symbol
            if mask.any():
                idx = self._positions.index[mask][0]
                self._positions.at[idx, "netQty"] = int(self._positions.at[idx, "netQty"]) + signed
                if signed > 0:
                    self._positions.at[idx, "buyQty"] = int(self._positions.at[idx, "buyQty"]) + int(qty)
                else:
                    self._positions.at[idx, "sellQty"] = int(self._positions.at[idx, "sellQty"]) + int(qty)
            else:
                self._positions = pd.concat(
                    [self._positions, pd.DataFrame([row])],
                    ignore_index=True,
                )
        return oid

    def place_aggressive_limit(
        self,
        symbol,
        qty,
        side,
        *,
        buffer_pct=10.0,
        tick_size=0.05,
        chase_timeout_sec=45.0,
        chase_interval_sec=5.0,
        trade_type="MARGIN",
        exchange="NFO",
    ):
        """Test double — same book effect as market; records LIMIT kwargs."""
        del buffer_pct, tick_size, chase_timeout_sec, chase_interval_sec, exchange
        return self.place_market_order(symbol, qty, side, trade_type=trade_type)

    def modify_order(self, order_id, *, order_type="LIMIT", qty, price, trigger_price=0):
        return str(order_id)

    def get_order_status(self, order_id):
        return "TRADED"

    def cancel_order(self, order_id):
        return "CANCELLED"

    def cancel_all_intraday(self):
        pass

    # Positions & P&L
    def set_position(self, symbol: str, net_qty: int) -> None:
        """Test helper — set absolute net long qty for a symbol."""
        import pandas as pd

        row = {
            "tradingSymbol": symbol,
            "netQty": int(net_qty),
            "buyQty": int(net_qty) if net_qty > 0 else 0,
            "sellQty": 0,
        }
        if self._positions.empty:
            self._positions = pd.DataFrame([row])
            return
        mask = self._positions["tradingSymbol"] == symbol
        if mask.any():
            idx = self._positions.index[mask][0]
            self._positions.at[idx, "netQty"] = int(net_qty)
            self._positions.at[idx, "buyQty"] = int(net_qty) if net_qty > 0 else 0
        else:
            self._positions = pd.concat(
                [self._positions, pd.DataFrame([row])],
                ignore_index=True,
            )

    def get_positions(self):
        return self._positions

    def get_live_pnl(self):
        return self._pnl

    def get_balance(self):
        return self._balance

    def get_orderbook(self):
        return pd.DataFrame(self._orders)

    def close_position(self, symbol, qty, side, trade_type="MARGIN", exchange="NFO"):
        return self.place_market_order(symbol, qty, side, trade_type)

    def close_all_positions(self, trade_type="MARGIN"):
        return []

    def needs_reauth(self):
        return False

    def send_alert(self, message, chat_id, bot_token):
        pass

    @property
    def circuit_status(self):
        return {"name": "mock", "state": "CLOSED", "failure_count": 0}


@pytest.fixture(autouse=True)
def _reset_market_data_guard():
    from core.market_data_guard import reset_market_data_guard_for_tests

    reset_market_data_guard_for_tests()
    yield
    reset_market_data_guard_for_tests()


@pytest.fixture
def mock_broker():
    return MockBroker()


@pytest.fixture
def config():
    from core.config import Config

    cfg = Config.__new__(Config)
    cfg._data = {
        "broker": {
            "client_code": "TEST",
            "pin": "0000",
            "totp_secret": "TESTSECRET",
        },
        "telegram": {
            "bot_token": "TESTTOKEN",
            "chat_id": "12345",
        },
        "modules": {
            "ato_protection": {"enabled": True},
            "batman_entry": {"enabled": True},
            "profit_trailing": {"enabled": True},
            "ratripal": {"enabled": True},
            "overnight_hedge": {"enabled": True},
            "position_monitor": {"enabled": True},
            "emergency_exit": {"enabled": True},
        },
        "strategy": {
            "index": "NIFTY",
            "exchange": "NFO",
            "lot_size": 65,
            "entry_day": "Wednesday",
            "entry_time": "11:00",
            "expiry_day": "Tuesday",
            "sell_distance": 300,
            "hedge_gap": 250,
            "buy_lots": 1,
            "product_type": "MARGIN",
        },
        "ato": {
            "retrace_point_options": [5, 10, 35, 50],
            "poll_interval_seconds": 2,
        },
        "trailing": {
            "hard_stop_loss": -8000,
            "activation_profit": 12000,
            "trailing_distance": 2000,
            "check_interval_seconds": 5,
        },
        "hedge": {
            "distance_from_spot": 500,
            "lots": 1,
            "cutoff_time": "15:15",
        },
        "hedge_box": {
            "enabled": True,
            "check_time_ist": "15:15",
            "box_width_points": 75,
            "strike_step_points": 50,
            "use_ato_engaged_override": True,
            "ato_override_requires_outside_short": True,
            "default_opposite_side_mode": "standard_break_even",
            "white_zone_policy": "dual_standard_break_even",
            "quantity_mode": "deployed_buy_qty_per_side",
            "dte_source": "deployment_calendar",
            "single_checkpoint_only": True,
        },
        "monitor": {
            "report_interval_seconds": 300,
            "mtm_alert_threshold": -5000,
            "alert_on_negative": True,
        },
        "market": {
            "open_time": "09:15",
            "close_time": "15:30",
        },
    }
    return cfg


@pytest.fixture
def state(tmp_path):
    from core.state import StateManager

    return StateManager(path=tmp_path / "test_state.json")


@pytest.fixture
def event_bus():
    from core.event_bus import EventBus

    return EventBus()
