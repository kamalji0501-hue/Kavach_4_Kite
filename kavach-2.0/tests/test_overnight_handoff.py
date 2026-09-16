"""Overnight handoff qty isolation and 09:20 open branches."""

from datetime import time

from core.overnight_handoff import (
    ato_buffers_blocked,
    classify_open,
    evening_buy_allowed,
    morning_actions,
    morning_cutoff_reached,
    morning_handoff_due,
    morning_sell_qty,
    overnight_snapshot,
)


class _St:
    def __init__(self, d):
        self.d = d

    def get(self, k, default=None):
        return self.d.get(k, default)


def test_morning_sell_evening_qty_only_leaves_extras():
    # Evening filled 10 lots; book 15 (5 extra or 5 dyn hedge) -> sell 10.
    assert morning_sell_qty(stored_evening_qty=10 * 65, book_long=15 * 65) == 10 * 65


def test_morning_sell_never_shorts_if_lots_already_gone():
    assert morning_sell_qty(stored_evening_qty=10 * 65, book_long=8 * 65) == 8 * 65


def test_morning_sell_zero_when_nothing_stored():
    assert morning_sell_qty(stored_evening_qty=0, book_long=5 * 65) == 0


def test_classify_open_inside_and_gaps():
    assert classify_open(spot=24600, ce_trigger=24800, pe_trigger=24400) == "inside"
    assert classify_open(spot=24800, ce_trigger=24800, pe_trigger=24400) == "ce_out"
    assert classify_open(spot=24390, ce_trigger=24800, pe_trigger=24400) == "pe_out"
    assert classify_open(spot=24850, ce_trigger=24800, pe_trigger=24900) == "both_out"


def test_morning_cutoff_0920():
    assert morning_cutoff_reached(time(9, 19)) is False
    assert morning_cutoff_reached(time(9, 20)) is True
    assert morning_cutoff_reached(time(10, 0)) is True


def test_ato_blocked_while_overnight_active_until_morning_done():
    st = _St({"overnight.hedge_active": True, "overnight.morning_done_date": None})
    assert ato_buffers_blocked(st, "2026-09-11") is True
    st2 = _St({"overnight.hedge_active": True, "overnight.morning_done_date": "2026-09-11"})
    assert ato_buffers_blocked(st2, "2026-09-11") is False
    st3 = _St({"overnight.hedge_active": False})
    assert ato_buffers_blocked(st3, "2026-09-11") is False


def test_web_deny_blocks_evening_buy():
    assert evening_buy_allowed(denied=True) is False
    assert evening_buy_allowed(denied=False) is True
    snap = overnight_snapshot(
        _St(
            {
                "ratripal.pending.request_id": "req-1",
                "ratripal.pending.response": "deny",
                "ratripal.pending.sides": [{"side": "CE", "qty": 650}],
            }
        )
    )
    assert snap["denied"] is True
    assert snap["pending"] is False


def test_no_deny_pending_then_ato_skipped_after_fill():
    pending = overnight_snapshot(
        _St(
            {
                "ratripal.pending.request_id": "req-1",
                "ratripal.pending.response": None,
            }
        )
    )
    assert pending["pending"] is True
    assert evening_buy_allowed(denied=False) is True
    filled = _St({"overnight.hedge_active": True, "overnight.morning_done_date": None})
    assert ato_buffers_blocked(filled, "2026-09-11") is True


def test_morning_0920_inside_sells_only():
    assert morning_actions("inside") == ["sell_overnight", "ato_on"]
    assert "buy_ce_ato" not in morning_actions("inside")
    assert "buy_pe_ato" not in morning_actions("inside")


def test_morning_0920_ce_gap_buys_ce_then_sells():
    assert morning_actions("ce_out") == ["buy_ce_ato", "sell_overnight", "ato_on"]


def test_morning_0920_pe_gap_buys_pe_then_sells():
    assert morning_actions("pe_out") == ["buy_pe_ato", "sell_overnight", "ato_on"]


def test_morning_handoff_due_only_at_0920_while_active():
    st = _St({"overnight.hedge_active": True, "overnight.morning_done_date": None})
    assert morning_handoff_due(st, time(9, 19), "2026-09-11") is False
    assert morning_handoff_due(st, time(9, 20), "2026-09-11") is True
    done = _St({"overnight.hedge_active": True, "overnight.morning_done_date": "2026-09-11"})
    assert morning_handoff_due(done, time(9, 21), "2026-09-11") is False
    complete = _St(
        {
            "overnight.hedge_active": True,
            "deployment.batman_complete": True,
        }
    )
    assert morning_handoff_due(complete, time(9, 21), "2026-09-11") is False


def test_ratripal_buy_candidate_even_if_already_long(mock_broker, config, state, event_bus):
    from modules.ratripal import Ratripal, SidePlan

    mod = Ratripal(mock_broker, config, state, event_bus)
    plan = SidePlan(
        side="CE",
        state="White",
        action="standard_break_even",
        strike=24950,
        symbol="NIFTY25APR24950CE",
        quantity=650,
        break_even=24950,
        option_ltp=None,
    )
    mod._has_existing_long_position = lambda symbol, qty: True  # type: ignore[method-assign]
    assert mod._is_buy_candidate(plan) is True


def test_ratripal_records_evening_fill_not_book_total(mock_broker, config, state, event_bus):
    from modules.ratripal import Ratripal, SidePlan

    mod = Ratripal(mock_broker, config, state, event_bus)
    plan = SidePlan(
        side="CE",
        state="White",
        action="standard_break_even",
        strike=24950,
        symbol="NIFTY25APR24950CE",
        quantity=650,
        break_even=24950,
        option_ltp=None,
    )
    mod._record_overnight_fill(plan, 650)
    assert state.get("overnight.hedge_active") is True
    assert state.get("overnight.ce_qty") == 650
    assert state.get("overnight.ce_symbol") == "NIFTY25APR24950CE"


def test_hedge_box_web_deny_sets_pending_response(monkeypatch):
    class _S:
        def __init__(self):
            self.d = {"ratripal.pending.request_id": "req-9", "ratripal.pending.response": None}

        def get(self, k, default=None):
            return self.d.get(k, default)

        def set(self, k, v, save=True):
            self.d[k] = v

    st = _S()
    import web.commands as commands

    monkeypatch.setattr(commands, "_state", lambda: st)
    monkeypatch.setattr("core.desk_alerts.emit_desk_alert", lambda **kw: None)
    out = commands.hedge_box_deny()
    assert out["ok"] is True
    assert st.get("ratripal.pending.response") == "deny"
    blocked = commands.hedge_box_deny()
    assert blocked["ok"] is True


def test_overnight_cycle_entry_then_exit_impact():
    from core.overnight_handoff import (
        close_overnight_cycle_exit,
        overnight_cycles,
        record_overnight_cycle_entry,
        reset_overnight_cycles,
    )

    class _S:
        def __init__(self):
            self.d = {}
        def get(self, k, default=None):
            return self.d.get(k, default)
        def set(self, k, v, save=True):
            self.d[k] = v

    st = _S()
    reset_overnight_cycles(st)
    record_overnight_cycle_entry(
        st, side="CE", symbol="NIFTY25SEP24950CE", qty=650,
        entry_premium=40.0, entry_time="15:20:01", zone="White",
    )
    record_overnight_cycle_entry(
        st, side="PE", symbol="NIFTY25SEP23950PE", qty=650,
        entry_premium=35.0, entry_time="15:20:02", zone="White",
    )
    close_overnight_cycle_exit(
        st, side="CE", symbol="NIFTY25SEP24950CE",
        exit_premium=30.0, exit_time="09:20:05",
    )
    rows = overnight_cycles(st)
    assert len(rows) == 2
    ce = rows[0]
    assert ce["status"] == "closed"
    assert ce["impact"] == -10.0
    assert ce["impact_rupees"] == -6500.0
    assert rows[1]["status"] == "open"
