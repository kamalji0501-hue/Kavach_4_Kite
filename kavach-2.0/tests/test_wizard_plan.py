"""Tests for core.wizard_plan."""

from __future__ import annotations

from core.wizard_plan import (
    build_wizard_plan,
    max_wizard_question_count,
    question_index,
    rebuild_wizard_plan,
)


def test_max_question_count_both_sides():
    # PE+CE blocks (5+5) + poll + confirm — no Enable PE/CE prompts
    assert max_wizard_question_count() == 12


def test_build_plan_both_sides():
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    assert plan[0] == "pe_buy"
    assert plan[-1] == "confirm"
    assert "pe_intent" not in plan
    assert "ce_intent" not in plan
    assert "pe_ato_strike" in plan
    assert "ce_ato_strike" in plan
    assert len(plan) == 12


def test_build_plan_pe_only():
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=False)
    assert "ce_buy" not in plan
    assert "ce_ato_strike" not in plan
    assert "ce_intent" not in plan
    assert len(plan) == 7


def test_rebuild_after_pe_skip():
    wiz: dict = {"pe_enabled": False, "ce_enabled": None}
    plan = rebuild_wizard_plan(wiz)
    assert "pe_buy" not in plan
    assert len(plan) == 7


def test_question_index_confirm():
    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    idx, total = question_index(plan, "confirm")
    assert idx == 12
    assert total == 12
