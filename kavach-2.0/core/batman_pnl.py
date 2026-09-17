"""HOME Batman P&L = Day P&L + prior-day ATO summary ₹ + prior-day overnight hedge ₹.

Prior-day totals are the session summary footers as they stood after the previous
trading day's close (all closed cycles dated on/before that day).
"""

from __future__ import annotations

import csv
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("batman.batman_pnl")


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def previous_trading_day(today: date | None = None) -> date:
    from core import utils

    d = (today or utils.today_ist()) - timedelta(days=1)
    for _ in range(14):
        if utils.is_trading_day(d):
            return d
        d -= timedelta(days=1)
    return (today or utils.today_ist()) - timedelta(days=1)


def _deployment_name(state: Any) -> str | None:
    if state is None:
        return None
    try:
        if not bool(state.get("deployment.confirmed", False)):
            return None
        if bool(state.get("deployment.batman_complete", False)):
            return None
        raw = state.get("deployment.file")
    except Exception:
        return None
    if not raw:
        return None
    name = Path(str(raw)).name.strip()
    return name or None


def _cycle_date(row: dict[str, Any]) -> date | None:
    """Best date for overnight cycle attribution (entry date_ist, else exit/entry stamp)."""
    raw = str(row.get("date_ist") or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    for key in ("exit_time", "entry_time"):
        stamp = str(row.get(key) or "").strip()
        if len(stamp) >= 10 and stamp[4] == "-" and stamp[7] == "-":
            try:
                return date.fromisoformat(stamp[:10])
            except ValueError:
                continue
    return None


def ato_summary_rupees_asof(
    *,
    deployment_name: str | None,
    asof: date,
    ledger_path: Path | None = None,
) -> float:
    """Session ATO summary ₹ total as of prior trading day close (date_ist <= asof)."""
    if not deployment_name:
        return 0.0
    if ledger_path is None:
        try:
            from core.batman_mode import workspace_root
            from core.saransh_paths import ato_analytics_dir

            ledger_path = ato_analytics_dir(workspace_root()) / "ato_trade_ledger.csv"
        except Exception:
            return 0.0
    if not ledger_path or not ledger_path.is_file():
        return 0.0
    want = str(deployment_name).strip()
    total = 0.0
    try:
        with ledger_path.open(encoding="utf-8", newline="") as fh:
            for raw in csv.DictReader(fh):
                dep = str(raw.get("deployment_file") or "").strip()
                if dep != want and Path(dep).name != want:
                    continue
                d_raw = str(raw.get("date_ist") or "").strip()
                try:
                    d = date.fromisoformat(d_raw[:10])
                except ValueError:
                    continue
                if d > asof:
                    continue
                buy = _f(raw.get("buy_option_premium"))
                sell = _f(raw.get("sell_option_premium"))
                qty = _f(raw.get("qty")) or 0.0
                if buy is None or sell is None or buy <= 0 or sell <= 0 or qty == 0:
                    continue
                total += (float(sell) - float(buy)) * float(qty)
    except Exception as exc:
        logger.warning("ato prior-day summary failed: %s", exc)
        return 0.0
    return round(total, 2)


def overnight_summary_rupees_asof(*, state: Any, asof: date) -> float:
    """Overnight hedge summary ₹ as of prior day (closed cycles dated on/before asof)."""
    try:
        from core.overnight_handoff import overnight_cycles
    except Exception:
        return 0.0
    total = 0.0
    for row in overnight_cycles(state):
        if str(row.get("status") or "") != "closed":
            continue
        d = _cycle_date(row)
        if d is None or d > asof:
            continue
        rs = _f(row.get("impact_rupees"))
        if rs is None:
            impact = _f(row.get("impact"))
            qty = _f(row.get("qty")) or 0.0
            if impact is None:
                continue
            rs = float(impact) * float(qty)
        total += float(rs)
    return round(total, 2)


def compute_batman_pnl(
    *,
    state: Any,
    day_pnl: float | None,
    today: date | None = None,
) -> dict[str, Any]:
    from core import utils

    today = today or utils.today_ist()
    asof = previous_trading_day(today)
    dep = _deployment_name(state)
    day = 0.0 if day_pnl is None else float(day_pnl)
    ato_prev = ato_summary_rupees_asof(deployment_name=dep, asof=asof) if dep else 0.0
    oh_prev = overnight_summary_rupees_asof(state=state, asof=asof) if dep else 0.0
    total = round(day + ato_prev + oh_prev, 2)
    return {
        "batman_pnl": total if dep else (0.0 if day_pnl is not None else None),
        "day_pnl": day if dep else (0.0 if day_pnl is not None else None),
        "ato_prev_day_rupees": ato_prev,
        "overnight_prev_day_rupees": oh_prev,
        "asof_date": asof.isoformat(),
        "asof_label": f"prior trading day {asof.isoformat()}",
    }
