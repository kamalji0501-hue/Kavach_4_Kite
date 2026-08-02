"""Telegram notice before crash-exit halt (OQ-P1-22 — wired after SARANSH P0–P5)."""

from __future__ import annotations

import logging
from pathlib import Path

from core.batman_mode import workspace_root
from core.optional_bot_startup import optional_bot_enabled

logger = logging.getLogger(__name__)

_HALT_TEMPLATE = (
    "Process halted: {bot_name} exited after unrecoverable error.\n"
    "Restart via Execution\\Start Bots\\start {start_bat}."
)


def halt_notify_message(bot_name: str, *, error_summary: str = "") -> str:
    start_bat = {
        "drishti": "Drishti.bat",
        "kavach": "Kavach.bat",
        "kavach2": "Kavach2.bat",
        "jagran": "Jagran.bat",
        "saransh": "Saransh.bat",
    }.get(bot_name.lower(), f"{bot_name.title()}.bat")
    msg = _HALT_TEMPLATE.format(bot_name=bot_name.upper(), start_bat=start_bat)
    if error_summary:
        msg += f"\n\nError: {error_summary[:500]}"
    return msg


def halt_notify_targets(bot_name: str, *, root: Path | None = None) -> list[tuple[str, str]]:
    """
    Return [(token_env_key, chat_tier)] for halt Telegram.

    OQ-P1-22 A: core trio → Batman Alerts; SARANSH → Non Critical Alerts.
    """
    name = bot_name.lower()
    if name == "saransh":
        return [("saransh", "non_critical")]
    if name in {"drishti", "kavach", "kavach2", "jagran"}:
        return [(name if name != "kavach2" else "kavach2", "batman_alerts")]
    return []


def should_send_halt_telegram(bot_name: str, *, root: Path | None = None) -> bool:
    base = root or workspace_root()
    if bot_name.lower() == "saransh":
        ok, _ = optional_bot_enabled("saransh", root=base)
        return ok
    return True
