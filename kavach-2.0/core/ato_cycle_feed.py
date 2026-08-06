"""Fast JSONL + atomic state for SARANSH ATO cycle reporting (KAVACH hot path)."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from core.saransh_paths import ato_cycle_feed_path, ato_cycle_state_path

logger = logging.getLogger(__name__)
_FEED_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()


def _default_state() -> dict[str, Any]:
    return {
        "ce": {
            "holding": False,
            "holding_since_ist": None,
            "sell_strike": None,
            "protect_strike": None,
        },
        "pe": {
            "holding": False,
            "holding_since_ist": None,
            "sell_strike": None,
            "protect_strike": None,
        },
        "cycles_completed_today": 0,
        "net_point_impact": 0.0,
    }


def append_feed_event(event: dict[str, Any], *, root: Path | None = None) -> None:
    path = ato_cycle_feed_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False) + "\n"
    with _FEED_LOCK:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)


def read_cycle_state(*, root: Path | None = None) -> dict[str, Any]:
    path = ato_cycle_state_path(root)
    if not path.is_file():
        return _default_state()
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            base = _default_state()
            for side in ("ce", "pe"):
                side_raw = raw.get(side)
                if isinstance(side_raw, dict):
                    base[side].update(side_raw)
            base["cycles_completed_today"] = int(raw.get("cycles_completed_today", 0))
            base["net_point_impact"] = float(raw.get("net_point_impact", 0.0))
            if raw.get("updated_at_ist"):
                base["updated_at_ist"] = raw["updated_at_ist"]
            return base
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        logger.warning("ato_cycle_state read failed: %s", exc)
    return _default_state()


def write_cycle_state(state: dict[str, Any], *, root: Path | None = None) -> None:
    path = ato_cycle_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    with _STATE_LOCK:
        tmp.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp, path)


def record_ato_buy(
    *,
    side: str,
    sell_strike: int,
    buy_nifty_ltp: float,
    lots: float,
    timestamp_ist: str,
    deployment_file: str,
    root: Path | None = None,
    buy_option_premium: float | None = None,
    protect_strike: int | None = None,
) -> None:
    side_key = side.upper()
    event: dict[str, Any] = {
        "event": "ato_buy",
        "timestamp_ist": timestamp_ist,
        "side": side_key,
        "sell_strike": sell_strike,
        "buy_nifty_ltp": round(buy_nifty_ltp, 2),
        "lots": lots,
        "deployment_file": deployment_file,
    }
    if protect_strike is not None:
        event["protect_strike"] = int(protect_strike)
    if buy_option_premium is not None:
        event["buy_option_premium"] = round(float(buy_option_premium), 2)
    append_feed_event(event, root=root)
    state = read_cycle_state(root=root)
    leg = side_key.lower()
    state[leg] = {
        "holding": True,
        "holding_since_ist": timestamp_ist,
        "sell_strike": sell_strike,
        "protect_strike": int(protect_strike) if protect_strike is not None else None,
        "buy_nifty_ltp": round(buy_nifty_ltp, 2),
        "lots": lots,
        "deployment_file": deployment_file,
    }
    if buy_option_premium is not None:
        state[leg]["buy_option_premium"] = round(float(buy_option_premium), 2)
    state["updated_at_ist"] = timestamp_ist
    write_cycle_state(state, root=root)


def record_ato_cycle_complete(
    *,
    side: str,
    sell_strike: int,
    buy_nifty_ltp: float,
    sell_nifty_ltp: float,
    lots: float,
    timestamp_ist: str,
    deployment_file: str,
    root: Path | None = None,
    buy_timestamp_ist: str | None = None,
    buy_option_premium: float | None = None,
    sell_option_premium: float | None = None,
    premium_pnl: float | None = None,
    premium_pnl_rupees: float | None = None,
    protect_strike: int | None = None,
) -> float:
    point_impact = round(sell_nifty_ltp - buy_nifty_ltp, 2)
    event: dict[str, Any] = {
        "event": "cycle_complete",
        "timestamp_ist": timestamp_ist,
        "side": side.upper(),
        "sell_strike": sell_strike,
        "buy_nifty_ltp": round(buy_nifty_ltp, 2),
        "sell_nifty_ltp": round(sell_nifty_ltp, 2),
        "point_impact": point_impact,
        "lots": lots,
        "deployment_file": deployment_file,
    }
    if buy_timestamp_ist:
        event["buy_timestamp_ist"] = buy_timestamp_ist
    if protect_strike is not None:
        event["protect_strike"] = int(protect_strike)
    if buy_option_premium is not None:
        event["buy_option_premium"] = round(float(buy_option_premium), 2)
    if sell_option_premium is not None:
        event["sell_option_premium"] = round(float(sell_option_premium), 2)
    if premium_pnl is not None:
        event["premium_pnl"] = round(float(premium_pnl), 2)
    if premium_pnl_rupees is not None:
        event["premium_pnl_rupees"] = round(float(premium_pnl_rupees), 2)
    append_feed_event(event, root=root)
    state = read_cycle_state(root=root)
    leg = side.lower()
    state[leg] = {
        "holding": False,
        "holding_since_ist": None,
        "sell_strike": None,
        "protect_strike": None,
    }
    state["cycles_completed_today"] = int(state.get("cycles_completed_today", 0)) + 1
    state["net_point_impact"] = round(float(state.get("net_point_impact", 0.0)) + point_impact, 2)
    if premium_pnl is not None:
        state["net_premium_pnl"] = round(
            float(state.get("net_premium_pnl", 0.0)) + float(premium_pnl), 2
        )
    if premium_pnl_rupees is not None:
        state["net_premium_pnl_rupees"] = round(
            float(state.get("net_premium_pnl_rupees", 0.0)) + float(premium_pnl_rupees), 2
        )
    state["updated_at_ist"] = timestamp_ist
    write_cycle_state(state, root=root)
    return point_impact
