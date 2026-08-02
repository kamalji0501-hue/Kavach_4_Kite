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


def register_preamble() -> str:
    mode = get_mode()
    if mode == "uat":
        source = "Positions will load from the *UAT shadow book* (Sensibull / Cursor chat)."
    elif mode == "prod":
        source = "Positions will load from *Dhan* (live broker)."
    else:
        source = "Positions will load from *Dhan* (read-only on DEV)."
    return f"{environment_short_message()}\n\n{source}"
