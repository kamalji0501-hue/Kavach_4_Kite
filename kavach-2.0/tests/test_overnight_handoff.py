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
    convert_entry_premium,
    mark_overnight_converted_to_ato,
    overnight_matches_protect,
    overnight_open_entry_premium,
    overnight_session_totals,
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


def test_overnight_matches_protect_same_strike():
    assert overnight_matches_protect(
        overnight_symbol="NIFTY25SEP24500PE",
        protect_symbol="nifty25sep24500pe",
    )
    assert not overnight_matches_protect(
        overnight_symbol="NIFTY25SEP24500PE",
        protect_symbol="NIFTY25SEP24450PE",
    )
    assert not overnight_matches_protect(overnight_symbol="", protect_symbol="X")
    assert not overnight_matches_protect(overnight_symbol=None, protect_symbol=None)


def test_convert_overnight_to_ato_skips_sell_and_tops_up(monkeypatch):
    """Outside open + overnight on protect strike → keep/top-up, no overnight SELL."""
    from modules import ato_protection as ap_mod

    class _S:
        def __init__(self):
            self.d = {
                "overnight.hedge_active": True,
                "overnight.morning_done_date": None,
                "overnight.pe_symbol": "NIFTY25SEP24500PE",
                "overnight.pe_qty": 650,
                "overnight.ce_symbol": None,
                "overnight.ce_qty": 0,
                "ato.pe_protect_symbol": "NIFTY25SEP24500PE",
                "ato.pe_protect_strike": 24500,
                "deployment.batman_complete": False,
            }

        def get(self, k, default=None):
            return self.d.get(k, default)

        def set(self, k, v, save=True):
            self.d[k] = v

    st = _S()
    exits: list[str] = []
    converts: list[str] = []

    class _Fake:
        def __init__(self):
            self.state = st
            self.log = type("L", (), {"info": lambda *a, **k: None, "error": lambda *a, **k: None})()
            self.config = {"strategy.product_type": "MARGIN"}

        def _resolve_protect_symbol(self, side, *args):
            if side == "PE":
                return "NIFTY25SEP24500PE", 24500
            return "NIFTY25SEP24600CE", 24600

        def _convert_overnight_hedge_to_ato(self, side, *a, **k):
            converts.append(side)
            return True

        def _place_pe_protection(self, *a, **k):
            raise AssertionError("should convert, not place fresh PE ATO blindly")

        def _place_ce_protection(self, *a, **k):
            raise AssertionError("CE should not fire on pe_out")

        def _exit_overnight_side(self, side, sym_qty):
            exits.append(side)

    fake = _Fake()
    monkeypatch.setattr("core.utils.now_ist", lambda: __import__("datetime").datetime(2026, 9, 11, 9, 20, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Kolkata")))
    monkeypatch.setattr("core.desk_alerts.emit_desk_alert", lambda **kw: None)
    # bind unbound method
    ap_mod.ATOProtection._maybe_morning_overnight_handoff(
        fake,
        spot=24300.0,
        ce_settings={"trigger_level": 24800},
        pe_settings={"trigger_level": 24400},
        ce_strike=24750,
        pe_strike=24450,
        sym_qty={"NIFTY25SEP24500PE": 650},
    )
    assert converts == ["PE"]
    assert exits == ["CE"]  # CE overnight empty/skip path still called; PE skipped
    assert st.get("overnight.hedge_active") is False
    assert st.get("overnight.morning_done_date") == "2026-09-11"


def test_overnight_session_totals_accumulate_closed():
    from core.overnight_handoff import (
        close_overnight_cycle_exit,
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
        entry_premium=40.0, entry_time="2026-09-10 15:20:01", zone="White",
        date_ist="2026-09-10",
    )
    close_overnight_cycle_exit(
        st, side="CE", symbol="NIFTY25SEP24950CE",
        exit_premium=30.0, exit_time="2026-09-11 09:20:05",
    )
    record_overnight_cycle_entry(
        st, side="PE", symbol="NIFTY25SEP23950PE", qty=650,
        entry_premium=35.0, entry_time="2026-09-11 15:20:02", zone="White",
        date_ist="2026-09-11",
    )
    close_overnight_cycle_exit(
        st, side="PE", symbol="NIFTY25SEP23950PE",
        exit_premium=40.0, exit_time="2026-09-12 09:20:05",
    )
    tot = overnight_session_totals(st)
    assert tot["closed_count"] == 2
    assert tot["cycle_count"] == 2
    assert tot["total_impact"] == (-10.0 + 5.0)
    assert tot["total_rupees"] == round((-10.0 * 650) + (5.0 * 650), 2)


def test_convert_entry_premium_weighted_average():
    assert convert_entry_premium(
        overnight_px=40.0, overnight_qty=650, topup_px=None, topup_qty=0
    ) == 40.0
    # 650@40 + 650@50 = 45
    assert convert_entry_premium(
        overnight_px=40.0, overnight_qty=650, topup_px=50.0, topup_qty=650
    ) == 45.0


def test_overnight_open_entry_and_mark_converted():
    class _S:
        def __init__(self):
            self.d = {}
        def get(self, k, default=None):
            return self.d.get(k, default)
        def set(self, k, v, save=True):
            self.d[k] = v

    from core.overnight_handoff import record_overnight_cycle_entry, overnight_cycles, reset_overnight_cycles

    st = _S()
    reset_overnight_cycles(st)
    record_overnight_cycle_entry(
        st, side="PE", symbol="NIFTY25SEP23500PE", qty=650,
        entry_premium=42.5, entry_time="2026-09-17 15:20:11",
        zone="White", date_ist="2026-09-17",
    )
    px, ts, qty = overnight_open_entry_premium(
        st, side="PE", symbol="NIFTY25SEP23500PE"
    )
    assert px == 42.5
    assert qty == 650
    assert "15:20" in ts
    mark_overnight_converted_to_ato(
        st, side="PE", symbol="NIFTY25SEP23500PE", convert_time="2026-09-18 09:20:01"
    )
    rows = overnight_cycles(st)
    assert rows[0]["status"] == "closed"
    assert rows[0]["converted_to_ato"] is True
    assert rows[0]["impact"] is None
    assert rows[0]["entry_premium"] == 42.5
