"""Batman session cleanup — post-complete verification helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("batman.batman_cleanup")

POSITION_LEGS = ("pe_buy", "pe_sell", "ce_buy", "ce_sell")
HEDGE_LEGS = ("ce_margin_hedge", "ce_dyn_hedge", "pe_margin_hedge", "pe_dyn_hedge")

_ATO_NONE = (
    "ce_protect_symbol",
    "ce_protect_strike",
    "pe_protect_symbol",
    "pe_protect_strike",
    "ce_order_id",
    "pe_order_id",
    "ce_ato_exit_order_id",
    "pe_ato_exit_order_id",
    "ce_buy_oid",
    "pe_buy_oid",
    "ce_buy_qty",
    "pe_buy_qty",
    "ce_exit_qty",
    "pe_exit_qty",
    "ce_entry_option_premium",
    "pe_entry_option_premium",
    "ce_buy_trigger",
    "pe_buy_trigger",
    "ce_buy_limit",
    "pe_buy_limit",
    "ce_halt_reason",
    "pe_halt_reason",
    "web_buy_fill_token",
    "web_sell_fill_token",
    "ce_entry_replay_market_time",
    "pe_entry_replay_market_time",
)


def reset_state_after_complete(state: Any, *, save: bool = True) -> None:
    """Idle Kavach after Complete: no legs, no ATO levels, no leftover triggers."""
    if state is None:
        return
    for leg in POSITION_LEGS + HEDGE_LEGS:
        state.set(f"positions.{leg}", None, save=False)
    for key in _ATO_NONE:
        state.set(f"ato.{key}", None, save=False)
    state.set("ato.ce_triggered", False, save=False)
    state.set("ato.pe_triggered", False, save=False)
    state.set("ato.ce_ato_active", False, save=False)
    state.set("ato.pe_ato_active", False, save=False)
    state.set("ato.ce_awaiting_clearance", False, save=False)
    state.set("ato.pe_awaiting_clearance", False, save=False)
    state.set("ato.ce_side_halted", False, save=False)
    state.set("ato.pe_side_halted", False, save=False)
    state.set("ato.retrace_points", 5, save=False)
    state.set("ato.manage_sides", "both", save=False)
    state.set("ato.ce_entry_buffer_points", 0, save=False)
    state.set("ato.pe_entry_buffer_points", 0, save=False)
    state.set("ato.ce_retrace_points", 5, save=False)
    state.set("ato.pe_retrace_points", 5, save=False)
    state.set("dyn_hedge.pe_exited_date", None, save=False)
    state.set("dyn_hedge.ce_exited_date", None, save=False)
    state.set("dyn_hedge.exit_enabled", False, save=False)
    state.set("risk.break_even.pe", None, save=False)
    state.set("risk.break_even.ce", None, save=False)
    state.set("risk.break_even.confirmed", False, save=False)
    state.set("risk.break_even.source.pe", None, save=False)
    state.set("risk.break_even.source.ce", None, save=False)
    state.set("risk.break_even.skipped", False, save=False)
    state.set("deployment.confirmed", False, save=False)
    state.set("deployment.file", None, save=False)
    state.set("deployment.registration_scope", None, save=False)
    state.set("deployment.batman_complete", True, save=False)
    state.set("deployment.positions_confirmed_date", None, save=False)
    state.set("deployment.next_entry_date", None, save=False)
    state.set("deployment.cleanup_failed", False, save=False)
    state.set("algo.paused", False, save=False)
    state.set("algo.pause_reason", None, save=False)
    state.set("algo.paused_at", None, save=False)
    state.set("algo.paused_by", None, save=False)
    state.set("session.emergency_exited", False, save=False)
    state.set("pnl_exit.last_reason", None, save=False)
    state.set("pnl_exit.last_pnl", None, save=False)
    state.set("pnl_exit.last_at", None, save=False)
    state.set("pnl_exit.firing", False, save=False)
    if save:
        state.save()
    try:
        from core.ato_cycle_feed import reset_open_holdings

        reset_open_holdings()
    except Exception as exc:
        logger.warning("reset open ATO holdings failed: %s", exc)
    try:
        from core.day_pnl_cache import reset_day_pnl_after_complete

        reset_day_pnl_after_complete()
        logger.info("DAY PNL reset after Batman complete")
    except Exception as exc:
        logger.warning("DAY PNL reset after complete failed: %s", exc)


def verify_batman_cleanup(
    *,
    deploy_dir: Path,
    state_get: Callable[[str], Any] | None = None,
) -> tuple[bool, list[tuple[str, bool]]]:
    """Return (all_ok, checklist) after batman_complete cleanup."""
    checks: list[tuple[str, bool]] = []

    active_files = sorted(deploy_dir.glob("batman_*.json"))
    checks.append(("No active deployment file in data/deployments", len(active_files) == 0))

    if state_get is not None:
        checks.append(("deployment.confirmed cleared", not bool(state_get("deployment.confirmed"))))
        checks.append(("deployment.file cleared", state_get("deployment.file") in (None, "")))
        legs_clear = all(state_get(f"positions.{leg}") is None for leg in POSITION_LEGS)
        checks.append(("Position legs cleared from state", legs_clear))
        ato_idle = not bool(state_get("ato.ce_triggered")) and not bool(
            state_get("ato.pe_triggered")
        )
        checks.append(("ATO trigger flags reset", ato_idle))
        checks.append(("batman_complete flag set", bool(state_get("deployment.batman_complete"))))

    all_ok = all(ok for _, ok in checks)
    return all_ok, checks


def run_cleanup_with_retries(
    *,
    cleanup_fn: Callable[[], tuple[list[str], bool, list[tuple[str, bool]]]],
    max_attempts: int = 3,
    delay_seconds: float = 0.5,
) -> tuple[list[str], bool, list[tuple[str, bool]], int]:
    """Run cleanup_fn until verify passes or attempts exhausted."""
    attempts = max(1, int(max_attempts))
    moved: list[str] = []
    all_ok = False
    checks: list[tuple[str, bool]] = []
    used = 0
    for used in range(1, attempts + 1):
        moved, all_ok, checks = cleanup_fn()
        if all_ok:
            break
        if used < attempts:
            time.sleep(delay_seconds)
    return moved, all_ok, checks, used


def open_ato_protect_lines(
    *,
    dep_data: dict[str, Any] | None,
    broker_symbols_qty: dict[str, int],
) -> list[str]:
    """Human-readable open ATO protect legs still on book."""
    if not dep_data:
        return []
    ato = dep_data.get("ato") or {}
    lines: list[str] = []
    for side, sym_key, strike_key in (
        ("CE", "ce_protect_symbol", "ce_protect_strike"),
        ("PE", "pe_protect_symbol", "pe_protect_strike"),
    ):
        sym = ato.get(sym_key)
        if not sym:
            continue
        qty = broker_symbols_qty.get(str(sym), 0)
        if qty > 0:
            strike = ato.get(strike_key, "?")
            lines.append(f"{side} ATO: {sym} — {qty} qty (strike {strike})")
    return lines


def format_cleanup_verification_message(
    *,
    all_ok: bool,
    checks: list[tuple[str, bool]],
    registered_at: str,
    completed_at: str,
    archived_file: str,
    open_ato_lines: list[str] | None = None,
    auto_register: bool = False,
) -> str:
    """MarkdownV2-ready cleanup confirmation for Telegram."""
    from telegram.helpers import escape_markdown

    def _code(value: str) -> str:
        return escape_markdown(str(value), version=2, entity_type="code")

    def _text(value: str) -> str:
        return escape_markdown(str(value), version=2)

    lines = [
        (
            "✅ *Batman Complete — Cleanup Verified*"
            if all_ok
            else "⚠️ *Batman Complete — Review Required*"
        ),
        "",
        "🦇 *Deployment Summary*",
        f"Deployed  : `{_code(registered_at)}`",
        f"Completed : `{_code(completed_at)}`",
        "",
        "🧹 *Verification*",
    ]
    for label, ok in checks:
        mark = "✅" if ok else "❌"
        lines.append(f"{mark} {_text(label)}")
    if open_ato_lines:
        lines.extend(["", "⚠️ *Open ATO legs on broker* _(not closed by Complete)_"])
        for row in open_ato_lines:
            lines.append(f"• {_text(row)}")
    lines.extend(
        [
            "",
            f"📁 Archived: `{_code(archived_file)}`",
            "",
        ]
    )
    if all_ok:
        if auto_register:
            lines.append("🟢 *Cleanup verified — starting registration…*")
        else:
            lines.append("🟢 *Ready to re\\-register*")
            lines.append("_Run /register when your next positions are on Dhan\\._")
    else:
        lines.append("⚠️ *Cleanup failed after retries — fix before /register\\.*")
    return "\n".join(lines)
