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
