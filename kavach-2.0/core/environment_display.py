#!/usr/bin/env python3
"""Short environment labels for KAVACH (dev | uat | prod)."""

from __future__ import annotations

from core.batman_mode import get_mode, prod_hostname_guard, workspace_root


def environment_label() -> str:
    mode = get_mode()
    labels = {
        "dev": "DEV",
        "uat": "UAT (virtual)",
        "prod": "PROD (live)",
    }
    return labels.get(mode, mode.upper())


def environment_short_message() -> str:
    """Plain-text / HTML-friendly environment blurb (not MarkdownV2)."""
    mode = get_mode()
    if mode == "dev":
        return "Environment: DEV — live NIFTY read-only; orders blocked on laptop."
    if mode == "uat":
        return (
            "Environment: UAT (virtual) — positions from Sensibull screenshot; "
            "orders simulated (no Dhan POST)."
        )
    warn = prod_hostname_guard()
    base = "Environment: PROD (live) — real Dhan positions and orders."
    if warn:
        return f"{base}\n\nWarning: {warn}"
    return base


def _md2_plain(text: str) -> str:
    """Escape Telegram MarkdownV2 reserved chars in plain segments."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(("\\" + c) if c in special else c for c in str(text))


def environment_short_message_md2() -> str:
    """Same as environment_short_message but safe for ParseMode.MARKDOWN_V2."""
    return _md2_plain(environment_short_message())


def register_preamble() -> str:
    """MarkdownV2 preamble shown after Paper/Live is chosen."""
    mode = get_mode()
    if mode == "uat":
        source = (
            "Positions will load from the *UAT shadow book* "
            + _md2_plain("(Sensibull / Cursor chat).")
        )
    elif mode == "prod":
        source = "Positions will load from *Dhan* " + _md2_plain("(live broker).")
    else:
        source = "Positions will load from *Dhan* " + _md2_plain("(read-only on DEV).")
    return f"{environment_short_message_md2()}\n\n{source}"
