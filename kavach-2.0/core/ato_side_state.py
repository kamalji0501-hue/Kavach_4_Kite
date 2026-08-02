"""Per-side ATO halt flags (CE / PE independent)."""

from __future__ import annotations

from typing import Any, Literal

Side = Literal["CE", "PE"]

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
    state.set(f"ato.{_prefix(side)}_side_halted", True, save=False)
    state.set(f"ato.{_prefix(side)}_halt_reason", reason, save=False)
    if save:
        state.save()


def clear_side_halt(state: Any, side: str, *, save: bool = True) -> None:
    if state is None:
        return
    state.set(f"ato.{_prefix(side)}_side_halted", False, save=False)
    state.set(f"ato.{_prefix(side)}_halt_reason", None, save=False)
    if save:
        state.save()


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
