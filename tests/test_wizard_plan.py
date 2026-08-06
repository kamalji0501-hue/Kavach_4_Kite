"""Tests for core.wizard_plan."""

from __future__ import annotations

from core.wizard_plan import (
    build_wizard_plan,
    max_wizard_question_count,
    question_index,
    rebuild_wizard_plan,
)


def test_max_question_count_both_sides():
    # order_mode + 7 PE + 7 CE + poll + confirm
    assert max_wizard_question_count() == 17


def test_build_plan_both_sides():
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    assert plan[0] == "order_mode"
    assert plan[-1] == "confirm"
    assert "pe_ato_strike" in plan
    assert "ce_ato_strike" in plan
    assert len(plan) == 17


def test_build_plan_pe_only():
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=False)
    assert plan[0] == "order_mode"
    assert "ce_buy" not in plan
    assert "ce_ato_strike" not in plan
    assert "pe_buy" in plan
    assert len(plan) == 10  # order_mode + 7 PE + poll + confirm


def test_rebuild_after_pe_skip():
    wiz: dict = {"pe_enabled": False, "ce_enabled": None}
    plan = rebuild_wizard_plan(wiz)
    assert plan[0] == "order_mode"
    assert "pe_buy" not in plan
    assert len(plan) == 10  # order_mode + 7 CE + poll + confirm


def test_question_index_confirm():
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    idx, total = question_index(plan, "confirm")
    assert idx == 17
    assert total == 17


def test_question_index_order_mode_is_first():
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    idx, total = question_index(plan, "order_mode")
    assert idx == 1
    assert total == 17
