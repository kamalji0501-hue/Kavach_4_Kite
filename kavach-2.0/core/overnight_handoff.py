"""Overnight Hedge Box handoff — evening fill qty and 09:20 open decision.

Pure helpers. Morning SELL is the evening overnight fill per side only.
Never sell extra lots or 35% dyn hedge on the same strike.
If overnight symbol == ATO protect on an outside open, convert (keep/top-up)
and do not sell that symbol in the overnight exit.
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




def overnight_open_entry_premium(
    state: Any,
    *,
    side: str,
    symbol: str,
) -> tuple[float | None, str, int]:
    """Return (entry_premium, entry_time, qty) for the open overnight cycle on symbol."""
    want_side = str(side or "").upper()
    want_sym = str(symbol or "").strip().upper()
    for row in reversed(overnight_cycles(state)):
        if str(row.get("status") or "") != "open":
            continue
        if str(row.get("side") or "").upper() != want_side:
            continue
        if want_sym and str(row.get("symbol") or "").strip().upper() != want_sym:
            continue
        try:
            px = float(row.get("entry_premium")) if row.get("entry_premium") is not None else None
        except (TypeError, ValueError):
            px = None
        if px is not None and px <= 0:
            px = None
        try:
            qty = int(row.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        return px, str(row.get("entry_time") or ""), qty
    return None, "", 0


def mark_overnight_converted_to_ato(
    state: Any,
    *,
    side: str,
    symbol: str,
    convert_time: str,
) -> None:
    """Close overnight cycle as converted — P&L continues on ATO Summary."""
    rows = overnight_cycles(state)
    want = str(side or "").upper()
    want_sym = str(symbol or "").strip().upper()
    for row in reversed(rows):
        if str(row.get("side") or "").upper() != want:
            continue
        if str(row.get("status") or "") != "open":
            continue
        if want_sym and str(row.get("symbol") or "").strip().upper() != want_sym:
            continue
        row["exit_time"] = convert_time
        row["exit_premium"] = None
        row["impact"] = None
        row["impact_rupees"] = None
        row["status"] = "closed"
        row["converted_to_ato"] = True
        row["zone"] = str(row.get("zone") or "")
        row["note"] = "converted_to_ato — P&L on ATO Summary"
        break
    try:
        state.set("overnight.cycles", rows)
    except Exception:
        pass


def convert_entry_premium(
    *,
    overnight_px: float | None,
    overnight_qty: int,
    topup_px: float | None,
    topup_qty: int,
) -> float | None:
    """Weighted average entry when overnight lots are kept and ATO tops up."""
    legs: list[tuple[float, int]] = []
    if overnight_px is not None and overnight_px > 0 and overnight_qty > 0:
        legs.append((float(overnight_px), int(overnight_qty)))
    if topup_px is not None and topup_px > 0 and topup_qty > 0:
        legs.append((float(topup_px), int(topup_qty)))
    if not legs:
        return overnight_px if overnight_px and overnight_px > 0 else topup_px
    num = sum(px * qty for px, qty in legs)
    den = sum(qty for _, qty in legs)
    if den <= 0:
        return None
    return round(num / float(den), 4)


def overnight_matches_protect(*, overnight_symbol: Any, protect_symbol: Any) -> bool:
    """True when evening overnight hedge is already sitting on the ATO protect strike."""
    a = str(overnight_symbol or "").strip().upper()
    b = str(protect_symbol or "").strip().upper()
    return bool(a and b and a == b)


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


def morning_handoff_completed_today(state: Any, today_iso: str) -> bool:
    """True after 09:20 overnight exit finished today — ATO may start before 09:25."""
    if state is None:
        return False
    try:
        done = str(state.get("overnight.morning_done_date") or "")
    except Exception:
        return False
    return done == str(today_iso)


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
    rows = [dict(x) for x in raw] if isinstance(raw, list) else []
    for i, row in enumerate(rows, start=1):
        if row.get("session_cycle") is None:
            row["session_cycle"] = i
    return rows


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
    date_ist: str = "",
) -> None:
    rows = overnight_cycles(state)
    rows.append(
        {
            "side": str(side or "").upper(),
            "symbol": str(symbol or ""),
            "qty": int(qty or 0),
            "date_ist": str(date_ist or ""),
            "entry_time": entry_time,
            "entry_premium": entry_premium,
            "exit_time": "",
            "exit_premium": None,
            "impact": None,
            "impact_rupees": None,
            "zone": zone or "",
            "status": "open",
            "session_cycle": len(rows) + 1,
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



def overnight_session_totals(state: Any) -> dict[str, Any]:
    """Cumulative overnight hedge P&L from Register until Complete."""
    rows = overnight_cycles(state)
    closed = [r for r in rows if str(r.get("status") or "") == "closed"]
    # also count converted (closed with null impact) in cycle count but not PnL
    impacts = []
    rupees = []
    for r in closed:
        try:
            if r.get("impact") is None or r.get("impact") == "":
                continue
            impacts.append(float(r.get("impact")))
        except (TypeError, ValueError):
            continue
        try:
            if r.get("impact_rupees") is not None and r.get("impact_rupees") != "":
                rupees.append(float(r.get("impact_rupees")))
        except (TypeError, ValueError):
            pass
    return {
        "cycle_count": len(rows),
        "closed_count": len(closed),
        "total_impact": round(sum(impacts), 2) if impacts else 0.0,
        "total_rupees": round(sum(rupees), 2) if rupees else 0.0,
    }


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
        "session_totals": overnight_session_totals(state),
    }
