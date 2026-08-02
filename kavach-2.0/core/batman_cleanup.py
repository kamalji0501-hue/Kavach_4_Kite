"""Batman session cleanup — post-complete verification helpers."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

POSITION_LEGS = ("pe_buy", "pe_sell", "ce_buy", "ce_sell")


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
