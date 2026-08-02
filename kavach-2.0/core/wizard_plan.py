"""KAVACH 2.0 /register wizard — dynamic question plan and numbering."""

from __future__ import annotations

from typing import Literal

Section = Literal["PE", "CE", "Shared"]

_STEP_META: dict[str, tuple[Section, str]] = {
    "pe_intent": ("PE", "PE side"),
    "pe_buy": ("PE", "Select Core PE BUY leg"),
    "pe_sell": ("PE", "Select PE SELL leg"),
    "pe_ato_strike": ("PE", "ATO strike"),
    "pe_entry": ("PE", "Entry NIFTY level"),
    "pe_exit": ("PE", "Exit NIFTY level (retrace)"),
    "ce_intent": ("CE", "CE side"),
    "ce_buy": ("CE", "Select Core CE BUY leg"),
    "ce_sell": ("CE", "Select CE SELL leg"),
    "ce_ato_strike": ("CE", "ATO strike"),
    "ce_entry": ("CE", "Entry NIFTY level"),
    "ce_exit": ("CE", "Exit NIFTY level (retrace)"),
    "poll": ("Shared", "Poll interval"),
    "confirm": ("Shared", "Confirm deployment"),
}

_PE_BLOCK = (
    "pe_buy",
    "pe_sell",
    "pe_ato_strike",
    "pe_entry",
    "pe_exit",
)
_CE_BLOCK = (
    "ce_buy",
    "ce_sell",
    "ce_ato_strike",
    "ce_entry",
    "ce_exit",
)
_SHARED = ("poll", "confirm")


def max_wizard_question_count() -> int:
    """Both sides enabled — includes confirm."""
    return len(build_wizard_plan(pe_enabled=True, ce_enabled=True))


def build_wizard_plan(
    *,
    pe_enabled: bool,
    ce_enabled: bool,
) -> list[str]:
    """Build ordered step ids; includes confirm as the last question.

    PE/CE enable prompts are skipped in Kavach 2.0 — sides are auto-detected
    from open legs, so the plan starts at leg pick.
    """
    steps: list[str] = []
    if pe_enabled:
        steps.extend(_PE_BLOCK)
    if ce_enabled:
        steps.extend(_CE_BLOCK)
    steps.extend(_SHARED)
    return steps


def rebuild_wizard_plan(wiz: dict) -> list[str]:
    """Recompute plan from wizard side flags (None → assume enabled for upper bound)."""
    pe = wiz.get("pe_enabled")
    ce = wiz.get("ce_enabled")
    plan = build_wizard_plan(
        pe_enabled=True if pe is None else bool(pe),
        ce_enabled=True if ce is None else bool(ce),
    )
    wiz["wiz_plan"] = plan
    return plan


def question_index(plan: list[str], step_id: str) -> tuple[int, int]:
    """Return (1-based index, total) for step_id."""
    total = len(plan)
    try:
        return plan.index(step_id) + 1, total
    except ValueError:
        return 1, total


def section_label(section: Section) -> str:
    if section == "Shared":
        return "Shared"
    return f"{section} side"


def step_meta(step_id: str) -> tuple[Section, str]:
    return _STEP_META.get(step_id, ("Shared", step_id))


def register_intro_text() -> str:
    n = max_wizard_question_count()
    return (
        "🦇 *Register wizard*\n\n"
        f"Up to *{n} questions* —\n"
        "Starting PE side"
    )
