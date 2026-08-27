"""ATO Trade Summary for the Kavach web desk (protect legs only)."""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger("batman.kavach.web.trade_summary")

def _broker_fill_map() -> dict[str, float]:
    """order_id → average_price from Kite order book (today session)."""
    out: dict[str, float] = {}
    try:
        from pathlib import Path as _P

        from core.batman_mode import workspace_root
        from core.zerodha_broker import ZerodhaBroker

        b = ZerodhaBroker.connect(root=workspace_root())
        rows = b._http.request("GET", "/orders") or []
    except Exception as exc:
        logger.debug("broker fill map unavailable: %s", exc)
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("order_id") or "").strip()
        if not oid:
            continue
        try:
            avg = float(row.get("average_price") or 0)
        except (TypeError, ValueError):
            avg = 0.0
        if avg > 0:
            out[oid] = avg
    return out




def _today_ist() -> str:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime

        return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    except Exception:
        return date.today().isoformat()


def _ledger_path() -> Path | None:
    try:
        from core.batman_mode import workspace_root
        from core.saransh_paths import ato_analytics_dir

        return ato_analytics_dir(workspace_root()) / "ato_trade_ledger.csv"
    except Exception as exc:
        logger.debug("ato analytics path failed: %s", exc)
        return None


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _closed_rows_today() -> list[dict[str, Any]]:
    path = _ledger_path()
    if not path or not path.is_file():
        return []
    today = _today_ist()
    fills = _broker_fill_map()
    out: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                if str(raw.get("date_ist") or "") != today:
                    continue
                side = str(raw.get("side") or "").upper()
                if side not in {"CE", "PE"}:
                    continue
                buy_oid = str(raw.get("buy_order_id") or "").strip()
                sell_oid = str(raw.get("sell_order_id") or "").strip()
                entry = fills.get(buy_oid) or _f(raw.get("buy_option_premium"))
                exitp = fills.get(sell_oid) or _f(raw.get("sell_option_premium"))
                if not entry or entry <= 0 or not exitp or exitp <= 0:
                    continue
                # ATO protect is always a long BUY then SELL exit — use broker fills.
                impact = float(exitp) - float(entry)
                qty = _i(raw.get("qty")) or 0
                rupees = round(float(impact) * float(qty), 2) if qty else None
                out.append(
                    {
                        "side": side,
                        "symbol": str(raw.get("protect_symbol") or "").strip(),
                        "protect_strike": _i(raw.get("protect_strike")),
                        "qty": qty,
                        "lots": _f(raw.get("lots")),
                        "entry_time": str(raw.get("buy_timestamp_ist") or ""),
                        "exit_time": str(raw.get("sell_timestamp_ist") or ""),
                        "entry_premium": entry,
                        "exit_premium": exitp,
                        "entry_nifty": _f(raw.get("buy_nifty_ltp")),
                        "exit_nifty": _f(raw.get("sell_nifty_ltp")),
                        "entry_trigger": _f(raw.get("entry_trigger_level")),
                        "exit_trigger": _f(raw.get("exit_trigger_level")),
                        "cycle_index": _i(raw.get("cycle_index")),
                        "buy_order_id": str(raw.get("buy_order_id") or ""),
                        "sell_order_id": str(raw.get("sell_order_id") or ""),
                        "impact": round(float(impact), 2),
                        "impact_rupees": round(float(rupees), 2) if rupees is not None else None,
                    }
                )
    except Exception as exc:
        logger.warning("trade summary ledger read failed: %s", exc)
        return []
    return out


def _open_ato_legs() -> list[dict[str, Any]]:
    """Open ATO protect holdings from live state (not Batman core / dyn hedge)."""
    try:
        from web.runtime import get_runtime

        rt = get_runtime()
        st = getattr(rt, "state", None) if rt else None
    except Exception:
        st = None
    if st is None:
        return []
    legs: list[dict[str, Any]] = []
    for side, prefix in (("CE", "ce"), ("PE", "pe")):
        active = bool(st.get(f"ato.{prefix}_ato_active", False))
        sym = st.get(f"ato.{prefix}_protect_symbol")
        if not active or not sym:
            continue
        legs.append(
            {
                "side": side,
                "symbol": str(sym),
                "protect_strike": st.get(f"ato.{prefix}_protect_strike"),
                "order_id": st.get(f"ato.{prefix}_order_id"),
                "triggered": bool(st.get(f"ato.{prefix}_triggered", False)),
                "status": "OPEN",
            }
        )
    return legs


def trade_summary() -> dict[str, Any]:
    closed = _closed_rows_today()
    open_legs = _open_ato_legs()
    total_impact = round(sum(float(r.get("impact") or 0) for r in closed), 2)
    total_rupees = round(
        sum(float(r["impact_rupees"]) for r in closed if r.get("impact_rupees") is not None),
        2,
    )
    return {
        "ok": True,
        "date_ist": _today_ist(),
        "open": open_legs,
        "closed": closed,
        "count": len(closed),
        "total_impact": total_impact,
        "total_rupees": total_rupees,
    }
