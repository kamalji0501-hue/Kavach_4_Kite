"""Overnight Hedge Box handoff — evening fill qty and 09:20 open decision.

Pure helpers. Morning SELL is the evening overnight fill per side only.
Never sell extra lots or 35% dyn hedge on the same strike.
"""

from __future__ import annotations

from datetime import time
from typing import Any

MORNING_CUTOFF = time(9, 20)


def morning_sell_qty(*, stored_evening_qty: int, book_long: int) -> int:
    """Sell only what Kavach filled last evening, never extra, never a short."""
    try:
        stored = max(0, int(stored_evening_qty or 0))
    except (TypeError, ValueError):
        stored = 0
    try:
        held = max(0, int(book_long or 0))
    except (TypeError, ValueError):
        held = 0
    return min(stored, held)


def classify_open(
    *,
    spot: float,
    ce_trigger: float | None,
    pe_trigger: float | None,
) -> str:
    """inside | ce_out | pe_out | both_out versus ATO triggers."""
    ce_out = ce_trigger is not None and float(spot) >= float(ce_trigger)
    pe_out = pe_trigger is not None and float(spot) <= float(pe_trigger)
    if ce_out and pe_out:
        return "both_out"
    if ce_out:
        return "ce_out"
    if pe_out:
        return "pe_out"
    return "inside"


def morning_cutoff_reached(now_t: time, *, cutoff: time = MORNING_CUTOFF) -> bool:
    return now_t >= cutoff


def morning_actions(kind: str) -> list[str]:
    """09:20 sequence. Inside: sell hedges then ATO on. Outside: ATO first."""
    if kind == "ce_out":
        return ["buy_ce_ato", "sell_overnight", "ato_on"]
    if kind == "pe_out":
        return ["buy_pe_ato", "sell_overnight", "ato_on"]
    if kind == "both_out":
        return ["buy_ce_ato", "buy_pe_ato", "sell_overnight", "ato_on"]
    return ["sell_overnight", "ato_on"]


def evening_buy_allowed(*, denied: bool) -> bool:
    """15:20 auto-buy unless the desk Denied."""
    return not bool(denied)


def morning_handoff_due(state: Any, now_t: time, today_iso: str) -> bool:
    """True once at 09:20 while overnight hedge is still on."""
    if state is None:
        return False
    try:
        if not bool(state.get("overnight.hedge_active", False)):
            return False
        if bool(state.get("deployment.batman_complete", False)):
            return False
        done = str(state.get("overnight.morning_done_date") or "")
    except Exception:
        return False
    if done == str(today_iso):
        return False
    return morning_cutoff_reached(now_t)


def ato_buffers_blocked(state: Any, today_iso: str) -> bool:
    """ATO buffer buy/sell off while overnight hedge is still on."""
    if state is None:
        return False
    try:
        active = bool(state.get("overnight.hedge_active", False))
    except Exception:
        return False
    if not active:
        return False
    try:
        done = str(state.get("overnight.morning_done_date") or "")
    except Exception:
        done = ""
    return done != str(today_iso)


def _summary_dict(state: Any) -> dict[str, Any]:
    try:
        raw = state.get("overnight.summary")
    except Exception:
        raw = None
    return dict(raw) if isinstance(raw, dict) else {}


def overnight_cycles(state: Any) -> list[dict[str, Any]]:
    if state is None:
        return []
    try:
        raw = state.get("overnight.cycles")
    except Exception:
        raw = None
    return [dict(x) for x in raw] if isinstance(raw, list) else []


def reset_overnight_cycles(state: Any) -> None:
    if state is None:
        return
    try:
        state.set("overnight.cycles", [])
        state.set("overnight.summary", {})
    except Exception:
        pass


def record_overnight_cycle_entry(
    state: Any,
    *,
    side: str,
    symbol: str,
    qty: int,
    entry_premium: float | None,
    entry_time: str,
    zone: str = "",
) -> None:
    rows = overnight_cycles(state)
    rows.append(
        {
            "side": str(side or "").upper(),
            "symbol": str(symbol or ""),
            "qty": int(qty or 0),
            "entry_time": entry_time,
            "entry_premium": entry_premium,
            "exit_time": "",
            "exit_premium": None,
            "impact": None,
            "impact_rupees": None,
            "zone": zone or "",
            "status": "open",
        }
    )
    try:
        state.set("overnight.cycles", rows)
    except Exception:
        pass


def close_overnight_cycle_exit(
    state: Any,
    *,
    side: str,
    symbol: str,
    exit_premium: float | None,
    exit_time: str,
) -> None:
    rows = overnight_cycles(state)
    want = str(side or "").upper()
    for row in reversed(rows):
        if str(row.get("side") or "").upper() != want:
            continue
        if str(row.get("status") or "") != "open":
            continue
        if symbol and row.get("symbol") and str(row.get("symbol")) != str(symbol):
            continue
        try:
            entry = float(row.get("entry_premium") or 0)
        except (TypeError, ValueError):
            entry = 0.0
        try:
            exitp = float(exit_premium or 0)
        except (TypeError, ValueError):
            exitp = 0.0
        try:
            qty = int(row.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        impact = (exitp - entry) if entry > 0 and exitp > 0 else None
        row["exit_time"] = exit_time
        row["exit_premium"] = exitp if exitp > 0 else None
        row["impact"] = impact
        row["impact_rupees"] = round(float(impact) * float(qty), 2) if impact is not None and qty else None
        row["status"] = "closed"
        break
    try:
        state.set("overnight.cycles", rows)
    except Exception:
        pass


def merge_overnight_summary(state: Any, **fields: Any) -> None:
    if state is None:
        return
    cur = _summary_dict(state)
    for key, value in fields.items():
        cur[key] = value
    try:
        state.set("overnight.summary", cur)
    except Exception:
        pass


def overnight_snapshot(state: Any) -> dict[str, Any]:
    if state is None:
        return {"active": False, "pending": False, "sides": []}
    pending_id = state.get("ratripal.pending.request_id")
    resp = state.get("ratripal.pending.response")
    sides = state.get("ratripal.pending.sides") or []
    return {
        "active": bool(state.get("overnight.hedge_active", False)),
        "ce_symbol": state.get("overnight.ce_symbol"),
        "ce_qty": int(state.get("overnight.ce_qty") or 0),
        "pe_symbol": state.get("overnight.pe_symbol"),
        "pe_qty": int(state.get("overnight.pe_qty") or 0),
        "buy_date": state.get("overnight.buy_date"),
        "morning_done_date": state.get("overnight.morning_done_date"),
        "pending": bool(pending_id) and resp not in {"deny", "confirm"},
        "denied": resp == "deny",
        "buy_time_ist": state.get("ratripal.pending.buy_time_ist") or "15:20",
        "sides": sides,
        "request_id": pending_id,
        "summary": _summary_dict(state),
        "cycles": overnight_cycles(state),
    }
