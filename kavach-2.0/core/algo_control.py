"""Shared algo pause/resume flags in batman_state.json (DRISHTI feed + KAVACH ATO)."""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime
from pathlib import Path

from core.batman_mode import state_path, workspace_root
from core.state import StateManager

logger = logging.getLogger("batman.algo_control")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def default_state_path() -> Path:
    """Mode-aware batman_state.json (UAT → data/uat/batman_state.json)."""
    return state_path(workspace_root())


def pause_algo(
    *,
    reason: str,
    paused_by: str = "drishti",
    state_path: Path | str | None = None,
) -> bool:
    """Set ``algo.paused`` True with audit fields. Returns True if newly paused."""
    sm = StateManager(path=Path(state_path) if state_path else default_state_path())
    if sm.get("algo.paused", False):
        logger.info("Algo already paused (reason=%s)", sm.get("algo.pause_reason"))
        return False

    now = datetime.now(_IST).isoformat()
    sm.set("algo.paused", True)
    sm.set("algo.pause_reason", reason)
    sm.set("algo.paused_at", now)
    sm.set("algo.paused_by", paused_by)
    logger.warning("Algo auto-paused by %s: %s", paused_by, reason)
    return True


def resume_algo(*, state_path: Path | str | None = None) -> bool:
    """Clear pause flags (operator Resume on KAVACH). Returns True if was paused."""
    sm = StateManager(path=Path(state_path) if state_path else default_state_path())
    if not sm.get("algo.paused", False):
        return False

    sm.set("algo.paused", False)
    sm.set("algo.pause_reason", None)
    sm.set("algo.paused_at", None)
    sm.set("algo.paused_by", None)
    logger.info("Algo resumed — pause flags cleared")
    return True


def is_algo_paused(state_path: Path | str | None = None) -> bool:
    sm = StateManager(path=Path(state_path) if state_path else default_state_path())
    return bool(sm.get("algo.paused", False))
