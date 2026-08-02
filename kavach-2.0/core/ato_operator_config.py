"""KAVACH ATO operator tunables — loaded from telegram/bots/kavach/params.json."""

from __future__ import annotations

from typing import Any

_DEFAULTS: dict[str, Any] = {
    "order_retry_max": 3,
    "cleanup_retry_max": 3,
    "soft_cap_first_warn_cycles": 3,
    "soft_cap_repeat_every_cycles": 2,
    "strike_presets_ce": [500, 1000],
    "strike_presets_pe": [100, 500],
    "monitor_breach_counts_toward_soft_cap": True,
    # SEBI/algo-safe market emulation for ATO protect BUY/SELL only.
    "limit_buffer_pct": 10.0,
    "limit_tick_size": 0.05,
    "limit_chase_timeout_sec": 45.0,
    "limit_chase_interval_sec": 5.0,
}


def ato_operator_settings(params: dict[str, Any] | None) -> dict[str, Any]:
    """Merge params['ato_operator'] over defaults."""
    raw = dict(_DEFAULTS)
    if params:
        section = params.get("ato_operator") or {}
        if isinstance(section, dict):
            for key in _DEFAULTS:
                if key in section:
                    raw[key] = section[key]
        deploy = params.get("deploy_wizard") or {}
        if isinstance(deploy, dict) and "ato_step" in deploy:
            raw["ato_step"] = int(deploy["ato_step"])
        strategy = params.get("strategy") or {}
        if isinstance(strategy, dict) and "lot_size" in strategy:
            raw["lot_size"] = int(strategy["lot_size"])
    raw.setdefault("ato_step", 50)
    raw.setdefault("lot_size", 65)
    return raw


def soft_cap_should_warn(
    *,
    cycle_count: int,
    breach_only_count: int,
    settings: dict[str, Any],
) -> bool:
    """Return True when operator should receive a choppy-session warning."""
    first = int(settings.get("soft_cap_first_warn_cycles", 3))
    repeat = int(settings.get("soft_cap_repeat_every_cycles", 2))
    if settings.get("monitor_breach_counts_toward_soft_cap", True):
        exposure = max(cycle_count, breach_only_count)
    else:
        exposure = cycle_count
    if exposure < first:
        return False
    if exposure == first:
        return True
    if repeat <= 0:
        return False
    return (exposure - first) % repeat == 0
