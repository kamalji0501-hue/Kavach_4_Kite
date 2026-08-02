"""Tests for KAVACH ATO operator tunables."""

from __future__ import annotations

from core.ato_operator_config import ato_operator_settings, soft_cap_should_warn


def test_ato_operator_settings_merges_defaults():
    op = ato_operator_settings({"ato_operator": {"order_retry_max": 5}})
    assert op["order_retry_max"] == 5
    assert op["soft_cap_first_warn_cycles"] == 3
    assert op["lot_size"] == 65


def test_soft_cap_first_warn_only_at_threshold():
    settings = {"soft_cap_first_warn_cycles": 3, "soft_cap_repeat_every_cycles": 2}
    assert soft_cap_should_warn(cycle_count=2, breach_only_count=0, settings=settings) is False
    assert soft_cap_should_warn(cycle_count=3, breach_only_count=0, settings=settings) is True


def test_soft_cap_repeat_every_two_after_first():
    settings = {
        "soft_cap_first_warn_cycles": 3,
        "soft_cap_repeat_every_cycles": 2,
        "monitor_breach_counts_toward_soft_cap": True,
    }
    assert soft_cap_should_warn(cycle_count=4, breach_only_count=0, settings=settings) is False
    assert soft_cap_should_warn(cycle_count=5, breach_only_count=0, settings=settings) is True
    assert soft_cap_should_warn(cycle_count=7, breach_only_count=0, settings=settings) is True


def test_soft_cap_uses_breach_only_when_higher():
    settings = {
        "soft_cap_first_warn_cycles": 3,
        "soft_cap_repeat_every_cycles": 2,
        "monitor_breach_counts_toward_soft_cap": True,
    }
    assert soft_cap_should_warn(cycle_count=1, breach_only_count=3, settings=settings) is True
