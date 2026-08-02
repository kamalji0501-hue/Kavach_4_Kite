"""Daily 09:25 IST 'run ATO today?' prompt — UAT skips (OQ-P1-08 / OQ-P1-16)."""

from __future__ import annotations

from pathlib import Path

from core.batman_mode import get_mode, is_uat


def should_send_daily_ato_prompt(root: Path | None = None) -> bool:
    """Return False in UAT — operator uses manual resume / register confirm instead."""
    return not is_uat(root)


def daily_ato_prompt_status_line(root: Path | None = None) -> str:
    mode = get_mode(root)
    if should_send_daily_ato_prompt(root):
        return f"Daily 09:25 ATO prompt: enabled (mode={mode})"
    return f"Daily 09:25 ATO prompt: skipped in UAT (mode={mode}) — use Resume / register confirm"
