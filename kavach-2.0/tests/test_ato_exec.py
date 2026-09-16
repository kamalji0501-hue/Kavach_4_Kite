"""Unit tests for ATO resting BUY + fill-Rescue math (no exchange)."""

from core.ato_exec import (
    aggressive_buy_limit,
    buy_trigger_limit,
    crash_sell_limit,
    remaining_qty,
    should_fill_rescue,
)


def test_buy_trigger_limit_ten_paise() -> None:
    trigger, limit = buy_trigger_limit(100.0)
    assert trigger == 100.0
    assert limit == 100.10


def test_fill_rescue_fires_at_plus_one() -> None:
    assert should_fill_rescue(trigger=100.0, ltp=101.0, remaining_qty=75) is True
    assert should_fill_rescue(trigger=100.0, ltp=100.50, remaining_qty=75) is False
    assert should_fill_rescue(trigger=100.0, ltp=101.0, remaining_qty=0) is False


def test_remaining_qty() -> None:
    assert remaining_qty(requested=150, filled=75) == 75
    assert remaining_qty(requested=150, filled=150) == 0


def test_aggressive_buy_is_ten_percent() -> None:
    px = aggressive_buy_limit(101.0)
    assert px >= 111.10


def test_crash_sell_is_seventy_percent_of_bid() -> None:
    px = crash_sell_limit(bid=100.0, ltp=100.0, pct=0.70)
    assert px == 70.0

from core.ato_exec import buy_chase_plan


def test_buy_chase_waits_while_first_order_open() -> None:
    plan = buy_chase_plan(
        registered_qty=130,
        order_status="OPEN",
        order_filled_qty=0,
        book_qty=0,
    )
    assert plan["action"] == "wait"
    assert plan["qty"] == 0


def test_buy_chase_waits_on_part_traded() -> None:
    plan = buy_chase_plan(
        registered_qty=130,
        order_status="PART_TRADED",
        order_filled_qty=65,
        book_qty=0,
    )
    assert plan["action"] == "wait"
    assert plan["qty"] == 0


def test_buy_chase_full_when_cancelled_and_flat() -> None:
    plan = buy_chase_plan(
        registered_qty=130,
        order_status="CANCELLED",
        order_filled_qty=0,
        book_qty=0,
    )
    assert plan["action"] == "chase"
    assert plan["qty"] == 130
    assert plan["reason"] == "cancelled_and_flat"


def test_buy_chase_remaining_after_partial_then_cancel() -> None:
    plan = buy_chase_plan(
        registered_qty=130,
        order_status="CANCELLED",
        order_filled_qty=65,
        book_qty=65,
    )
    assert plan["action"] == "chase"
    assert plan["qty"] == 65
    assert plan["reason"] == "cancelled_partial_remaining"


def test_buy_chase_remaining_after_partial_complete() -> None:
    plan = buy_chase_plan(
        registered_qty=130,
        order_status="COMPLETE",
        order_filled_qty=65,
        book_qty=65,
    )
    assert plan["action"] == "chase"
    assert plan["qty"] == 65


def test_buy_chase_done_when_registered_already_long() -> None:
    plan = buy_chase_plan(
        registered_qty=130,
        order_status="OPEN",
        order_filled_qty=0,
        book_qty=130,
    )
    assert plan["action"] == "done"
    assert plan["qty"] == 0


def test_buy_chase_never_exceeds_registered() -> None:
    plan = buy_chase_plan(
        registered_qty=65,
        order_status="CANCELLED",
        order_filled_qty=0,
        book_qty=0,
    )
    assert plan["qty"] == 65


def test_buy_chase_waits_when_status_unknown() -> None:
    plan = buy_chase_plan(
        registered_qty=130,
        order_status=None,
        order_filled_qty=None,
        book_qty=0,
    )
    assert plan["action"] == "wait"
    assert plan["qty"] == 0


def test_clearance_lock_stays_off(monkeypatch) -> None:
    from modules.ato_protection import ATOProtection

    class _State:
        def __init__(self):
            self.d = {}

        def get(self, k, default=None):
            return self.d.get(k, default)

        def set(self, k, v, save=True):
            self.d[k] = v

    state = _State()
    state.set("ato.ce_awaiting_clearance", True)
    state.set("ato.pe_awaiting_clearance", True)
    mod = ATOProtection.__new__(ATOProtection)
    mod.state = state
    logs = []

    class _Log:
        def info(self, *a, **k):
            logs.append(("info", a))

        def warning(self, *a, **k):
            logs.append(("warn", a))

    mod.log = _Log()
    settings = {"trigger_level": 24800, "exit_level": 24795, "entry_buffer": 0, "retrace_points": 5}
    mod._mark_awaiting_clearance_after_exit("CE", 24810.0, settings)
    mod._mark_awaiting_clearance_after_exit("PE", 24580.0, {"trigger_level": 24600})
    assert state.get("ato.ce_awaiting_clearance") is False
    assert state.get("ato.pe_awaiting_clearance") is False
    state.set("ato.ce_awaiting_clearance", True)
    mod._update_reentry_clearance("CE", 24850.0, settings)
    assert state.get("ato.ce_awaiting_clearance") is False

