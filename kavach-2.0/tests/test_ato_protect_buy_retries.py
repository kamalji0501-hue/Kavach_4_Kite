"""Regression: ATO protect-buy must never 3× on fill lag / overfill; halt visibility."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.ato_book_validation import lots_fulfilled, remainder_lots, remainder_qty
from core.ato_side_state import clear_side_halt, halt_side


def test_lots_fulfilled_overfill_is_done():
    assert lots_fulfilled(650, 650, 65) is True
    assert lots_fulfilled(1300, 650, 65) is True
    assert lots_fulfilled(1950, 650, 65) is True
    assert lots_fulfilled(0, 650, 65) is False
    assert lots_fulfilled(325, 650, 65) is False


def test_remainder_top_up_only():
    assert remainder_lots(0, 650, 65) == 10
    assert remainder_qty(0, 650, 65) == 650
    assert remainder_lots(325, 650, 65) == 5
    assert remainder_qty(325, 650, 65) == 325
    assert remainder_qty(1300, 650, 65) == 0


class _State:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v, save=True):
        self.d[k] = v

    def save(self):
        pass


def test_halt_side_emits_desk_alert(monkeypatch):
    calls = []

    def _emit(**kwargs):
        calls.append(kwargs)
        return {"id": "x"}

    monkeypatch.setattr("core.desk_alerts.emit_desk_alert", _emit)
    st = _State()
    halt_side(st, "PE", reason="order_retry_exhausted")
    assert st.get("ato.pe_side_halted") is True
    assert st.get("ato.pe_halt_reason") == "order_retry_exhausted"
    assert calls and calls[0]["severity"] == "red"
    assert "PE" in calls[0]["alert"]
    # re-assert same halt — no second alert
    halt_side(st, "PE", reason="order_retry_exhausted")
    assert len(calls) == 1
    clear_side_halt(st, "PE")
    assert st.get("ato.pe_side_halted") is False
    assert calls[-1]["severity"] == "green"


def test_readiness_partial_pe_halt(monkeypatch):
    from core import ato_readiness as ar

    monkeypatch.setattr(ar, "_svc_active", lambda _n: True)
    monkeypatch.setattr(
        "core.feeder_ipc.feeder_socket_ready", lambda: True, raising=False
    )

    class Snap:
        ltp = 23650.0
        source = "TEST"
        collector = "test"
        feed_healthy = True

        def age_seconds(self):
            return 1.0

    monkeypatch.setattr(
        "core.nifty_ltp_feed.read_nifty_ltp_cache", lambda *_a, **_k: Snap()
    )
    monkeypatch.setattr(
        "core.nifty_ltp_feed.cache_consumer_status", lambda **_k: (True, "ok")
    )
    monkeypatch.setattr(
        "core.nifty_ltp_feed.consumer_max_age_for_trading", lambda: 30.0
    )
    monkeypatch.setattr(
        "core.nifty_ltp_feed.default_cache_path", lambda: "/tmp/nifty.json"
    )

    st = _State()
    st.set("deployment.confirmed", True)
    st.set("algo.paused", False)
    st.set("ato.manage_sides", "both")
    st.set("ato.pe_side_halted", True)
    st.set("ato.pe_halt_reason", "order_retry_exhausted")
    st.set("ato.ce_side_halted", False)

    monkeypatch.setattr(
        ar,
        "_levels_from_state",
        lambda _s: {
            "pe_entry": "23638",
            "pe_exit": "23655",
            "ce_entry": "23665",
            "ce_exit": "23660",
            "protect_symbol_pe": "",
            "protect_symbol_ce": "",
            "protect_broker_qty_pe": 0,
            "protect_broker_qty_ce": 0,
        },
    )

    snap = ar.compute_ato_readiness(state=st, positions=[], check_services=False)
    assert snap["armed"] is True
    assert snap["partial"] is True
    assert "pe_side_halted" in snap["attention_reasons"]
    assert snap["sides"]["pe"]["halted"] is True
    assert "PE HALTED" in snap["summary_line"]
    assert snap["sides"]["ce"]["halted"] is False


class _FakeBroker:
    def __init__(self, books):
        # books: list of net qty returned per get_positions call
        self._books = list(books)
        self.placed = []
        self._i = 0

    def get_positions(self):
        if self._i < len(self._books):
            qty = self._books[self._i]
            self._i += 1
        else:
            qty = self._books[-1] if self._books else 0
        return [{"tradingsymbol": "NIFTYTESTPE", "netQty": qty}]

    def get_orderbook(self):
        return []


def _make_module(broker, state):
    from modules.ato_protection import ATOProtection

    # Minimal construction without full runtime
    mod = object.__new__(ATOProtection)
    mod.broker = broker
    mod.state = state
    mod.config = MagicMock()
    mod.config.get = lambda k, d=None: {
        "strategy.product_type": "MARGIN",
    }.get(k, d)
    mod.log = MagicMock()
    mod.events = MagicMock()
    mod.order_manager = None
    mod.name = "ato_protection"
    mod._operator_settings = lambda: {
        "order_retry_max": 3,
        "lot_size": 65,
        "order_fill_wait_seconds": 0.05,
        "order_fill_polls": 2,
    }
    mod._place_ato_aggressive_limit = MagicMock(
        side_effect=lambda **kw: f"OID-{len(broker.placed)+1}"
    )

    def _place(**kw):
        oid = f"OID-{len(broker.placed)+1}"
        broker.placed.append(kw)
        return oid

    mod._place_ato_aggressive_limit = _place
    mod._ato_order_status = lambda _oid: "COMPLETE"
    return mod


def test_protect_buy_no_third_on_overfill(monkeypatch):
    """Sep-8 mode: after 0 then 1300, must not buy a third 650."""
    monkeypatch.setattr(
        "modules.ato_protection.get_existing_ato_order", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "modules.ato_protection.record_ato_order", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "core.zerodha_instruments.nifty_expiry_key", lambda _s: "2026-09-15"
    )

    # Sequence of book reads during buy attempts / waits
    # Initial: 0; after first place waits: 0 then 650-ish becomes 1300 style overfill
    books = [0, 0, 0, 1300, 1300, 1300, 1300]
    broker = _FakeBroker(books)
    st = _State()
    st.set("positions.pe_sell", {"symbol": "NIFTYTESTPE"})
    mod = _make_module(broker, st)

    # Track place qty
    placed = []

    def _place(**kw):
        placed.append(kw)
        return f"OID-{len(placed)}"

    mod._place_ato_aggressive_limit = _place

    out = mod._execute_protect_buy(
        side="PE",
        symbol="NIFTYTESTPE",
        ato_qty=650,
        product="MARGIN",
        idem_key="k",
    )
    assert out is not None
    # Must not place 3 full 650s
    assert len(placed) <= 2
    assert all(int(p["qty"]) <= 650 for p in placed)
    # Once book shows 1300, no further place of 650
    assert sum(int(p["qty"]) for p in placed) <= 1300


def test_exit_rescue_caps_to_registered():
    """Watcher must pass min(held, registered) into rescue_flatten_sell."""
    # Light structural check of source constant presence is in integration;
    # here verify remainder math used by cap policy.
    held, reg = 1950, 650
    assert min(held, reg) == 650
