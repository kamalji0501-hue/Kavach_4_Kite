"""Per-side ATO halt flags (CE / PE independent)."""

from __future__ import annotations

import logging
from typing import Any, Literal

Side = Literal["CE", "PE"]

logger = logging.getLogger("batman.ato_side_state")

# Side halts cleared by operator /resume (Q55).
RESUMABLE_SIDE_HALT_REASONS = frozenset(
    {
        "manual_protect_full_exit",
        "manual_protect_partial_exit",
        "order_retry_exhausted",
    }
)


def _prefix(side: str) -> str:
    return "ce" if str(side).upper() == "CE" else "pe"


def is_side_halted(state: Any, side: str) -> bool:
    if state is None:
        return False
    if bool(state.get("algo.paused", False)):
        return True
    return bool(state.get(f"ato.{_prefix(side)}_side_halted", False))


def halt_side(state: Any, side: str, *, reason: str, save: bool = True) -> None:
    if state is None:
        return
    tag = str(side or "").strip().upper() or "PE"
    prefix = _prefix(tag)
    key_halt = f"ato.{prefix}_side_halted"
    key_reason = f"ato.{prefix}_halt_reason"
    was_halted = bool(state.get(key_halt, False))
    prev_reason = str(state.get(key_reason) or "")
    reason_s = str(reason or "halted").strip() or "halted"

    state.set(key_halt, True, save=False)
    state.set(key_reason, reason_s, save=False)
    if save:
        state.save()

    # Edge only — avoid spamming every poll that re-asserts the same halt.
    if was_halted and prev_reason == reason_s:
        return

    logger.error(
        "%s side HALTED reason=%s — %s will not buy until Resume. Check broker book.",
        tag,
        reason_s,
        tag,
    )
    try:
        from core.desk_alerts import emit_desk_alert

        emit_desk_alert(
            severity="red",
            category="Side halted",
            alert=(
                f"{tag} protection is halted ({reason_s}). "
                f"That side will not buy."
            ),
            log=(
                f"{tag} side HALTED reason={reason_s}. "
                "Pause then Resume after checking Zerodha positions."
            ),
            side=tag,
        )
    except Exception as exc:
        logger.debug("halt_side desk alert failed: %s", exc)


def clear_side_halt(state: Any, side: str, *, save: bool = True) -> None:
    if state is None:
        return
    tag = str(side or "").strip().upper() or "PE"
    prefix = _prefix(tag)
    key_halt = f"ato.{prefix}_side_halted"
    was_halted = bool(state.get(key_halt, False))
    prev_reason = str(state.get(f"ato.{prefix}_halt_reason") or "")

    state.set(key_halt, False, save=False)
    state.set(f"ato.{prefix}_halt_reason", None, save=False)
    if save:
        state.save()

    if not was_halted:
        return

    logger.info(
        "%s side resumed — monitoring again (cleared reason=%s).",
        tag,
        prev_reason or "halted",
    )
    try:
        from core.desk_alerts import emit_desk_alert

        emit_desk_alert(
            severity="green",
            category="Side halted",
            alert=f"{tag} side resumed — monitoring again.",
            log=f"{tag} side halt cleared (was {prev_reason or 'halted'}).",
            side=tag,
        )
    except Exception as exc:
        logger.debug("clear_side_halt desk alert failed: %s", exc)


def clear_all_side_halts(state: Any, *, save: bool = True) -> None:
    for side in ("CE", "PE"):
        clear_side_halt(state, side, save=False)
    if save and state is not None:
        state.save()


def pause_all_ato(state: Any, *, reason: str, save: bool = True) -> None:
    """Pause CE + PE monitoring (Q33 position book unreadable)."""
    if state is None:
        return
    state.set("algo.paused", True, save=False)
    state.set("algo.pause_reason", reason, save=False)
    if save:
        state.save()


def clear_resumable_side_halts(state: Any, *, save: bool = True) -> list[str]:
    """Clear per-side halts eligible for /resume (Q55). Returns cleared sides."""
    if state is None:
        return []
    cleared: list[str] = []
    for side in ("CE", "PE"):
        prefix = _prefix(side)
        if not state.get(f"ato.{prefix}_side_halted", False):
            continue
        reason = str(state.get(f"ato.{prefix}_halt_reason") or "")
        if reason in RESUMABLE_SIDE_HALT_REASONS:
            clear_side_halt(state, side, save=False)
            cleared.append(side.upper())
    if cleared and save:
        state.save()
    return cleared
