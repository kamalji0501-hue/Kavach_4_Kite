"""Shared day P&L + positions cache for Kavach Home.

Updated only when get_positions() already hits Kite (no extra REST).
Uses a sys.modules singleton so parent/core and kavach-2.0/core share one cache
even if both zerodha_broker copies are imported.

Day PnL matches Kite Positions Total P&L (sum of net[].pnl from get_positions).
Open-leg LTP may still refresh from /quote/ltp for display only.
"""

from __future__ import annotations

import sys
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any

_HOLDER = "_batman_day_pnl_cache_holder"
if _HOLDER not in sys.modules:
    sys.modules[_HOLDER] = SimpleNamespace(
        cache={"pnl": None, "ts": 0.0, "positions": []}
    )

_DAY_PNL_CACHE: dict[str, Any] = sys.modules[_HOLDER].cache  # type: ignore[attr-defined]
# Ensure older process holders gain the positions key.
_DAY_PNL_CACHE.setdefault("positions", [])


def _sum_pnl(rows: Any) -> float:
    total = 0.0
    if not rows:
        return total
    for r in rows:
        try:
            total += float((r or {}).get("pnl") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _f(row: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        if k in row and row.get(k) is not None:
            try:
                return float(row.get(k))
            except (TypeError, ValueError):
                continue
    return None


def _official_leg_pnl(row: dict[str, Any], *, ltp_override: float | None) -> tuple[float, float | None]:
    """Match Kite Positions Total: prefer broker `pnl` from get_positions().

    Only fall back to (sell_value - buy_value) + (qty * ltp * mult) when broker
    pnl is missing. Do not overwrite a present broker pnl with a local LTP
    rebuild — that drifts from Kite (especially after market close).
    """
    broker_pnl = _f(row, "pnl")
    ltp = ltp_override if ltp_override is not None else _f(row, "ltp")
    if ltp is None:
        ltp = _f(row, "avg")
    if broker_pnl is not None:
        return float(broker_pnl), ltp
    buy_value = _f(row, "buy_value")
    sell_value = _f(row, "sell_value")
    if buy_value is None or sell_value is None:
        return 0.0, ltp
    qty = float(row.get("qty") or 0)
    mult = _f(row, "multiplier")
    if mult is None:
        mult = 1.0
    if qty == 0:
        return float(sell_value) - float(buy_value), ltp
    if ltp is None:
        return 0.0, None
    return (float(sell_value) - float(buy_value)) + (qty * float(ltp) * float(mult)), float(ltp)


def _apply_official_pnl(row: dict[str, Any], *, ltp_override: float | None) -> float:
    pnl, ltp = _official_leg_pnl(row, ltp_override=ltp_override)
    row["pnl"] = float(pnl)
    qty = float(row.get("qty") or 0)
    if ltp is not None and qty != 0:
        row["ltp"] = float(ltp)
    return float(pnl)


def _compact_row(r: Any) -> dict[str, Any] | None:
    if not isinstance(r, dict):
        return None
    qty = _f(r, "quantity", "qty")
    if qty is None:
        qty = 0.0
    pnl = _f(r, "pnl")
    unrealised = _f(r, "unrealised", "unrealized")
    realised = _f(r, "realised", "realized")
    avg = _f(r, "average_price", "average", "avg")
    ltp = _f(r, "last_price", "ltp")
    buy_value = _f(r, "buy_value")
    sell_value = _f(r, "sell_value")
    multiplier = _f(r, "multiplier")
    if multiplier is None:
        multiplier = 1.0
    out = {
        "symbol": str(r.get("tradingsymbol") or r.get("symbol") or ""),
        "exchange": str(r.get("exchange") or ""),
        "product": str(r.get("product") or ""),
        "qty": qty,
        "avg": avg,
        "ltp": ltp,
        "pnl": pnl,
        "unrealised": unrealised,
        "realised": realised,
        "buy_value": buy_value,
        "sell_value": sell_value,
        "multiplier": multiplier,
    }
    official, _ltp_used = _official_leg_pnl(out, ltp_override=None)
    out["pnl"] = official
    return out


def _select_rows(net: Any) -> list[dict[str, Any]]:
    """Open legs first, then closed-for-day (qty==0, non-zero pnl) last."""
    raw = list(net or []) if isinstance(net, list) else []
    compact: list[dict[str, Any]] = []
    for r in raw:
        c = _compact_row(r)
        if c is not None:
            compact.append(c)
    open_rows: list[dict[str, Any]] = []
    closed_rows: list[dict[str, Any]] = []
    for c in compact:
        qty = float(c.get("qty") or 0)
        pnl = c.get("pnl")
        try:
            pnl_f = float(pnl) if pnl is not None else 0.0
        except (TypeError, ValueError):
            pnl_f = 0.0
        if qty != 0:
            row = dict(c)
            row["closed"] = False
            open_rows.append(row)
        elif abs(pnl_f) >= 0.005:
            row = dict(c)
            row["closed"] = True
            closed_rows.append(row)
    return open_rows + closed_rows


def update_day_pnl_from_positions(data: Any) -> None:
    """Prefer Kite net[] pnl (live MTM); fall back to day[] from the same response."""
    try:
        rows = None
        net = None
        if isinstance(data, dict):
            net = data.get("net")
            rows = net
            if not rows:
                rows = data.get("day")
        elif isinstance(data, list):
            rows = data
            net = data
        pnl = _sum_pnl(rows) if rows else 0.0
        broker_pnl = round(float(pnl), 2)
        _DAY_PNL_CACHE["broker_pnl"] = broker_pnl
        _DAY_PNL_CACHE["pnl"] = broker_pnl
        _DAY_PNL_CACHE["ts"] = time.time()
        # Positions list from net (preferred); fall back to day if net missing.
        src = net if net else rows
        compact = []
        for r in list(src or []):
            c = _compact_row(r)
            if c is not None:
                compact.append(c)
        _DAY_PNL_CACHE["positions"] = _select_rows(src)
        # All net legs for MTM — keep broker pnl on each row (matches Kite Total).
        _DAY_PNL_CACHE["pnl_rows"] = [
            c
            for c in compact
            if (c.get("qty") or 0) != 0
            or (c.get("pnl") is not None and float(c.get("pnl") or 0) != 0)
        ] or compact
        # Headline Day PnL = sum of raw Kite net[].pnl (same as Positions Total P&L).
        _DAY_PNL_CACHE["hybrid_pnl"] = broker_pnl
        _DAY_PNL_CACHE["pnl"] = broker_pnl
    except Exception:
        pass



_HYBRID_LTP_MIN_INTERVAL_S = 1.0


def _leg_hybrid_pnl(row: dict[str, Any], *, ltp_override: float | None) -> float:
    """Official Zerodha PnL; name kept for existing ATO refresh call sites."""
    return _apply_official_pnl(row, ltp_override=ltp_override)


def refresh_hybrid_day_pnl(*, broker: Any = None, force: bool = False) -> float | None:
    """Refresh open-leg LTPs for display; Day PnL stays on Kite broker pnl.

    Previously rebuilt pnl with a local LTP formula, which drifted from Kite
    Positions Total (seen after close / between polls). Keep broker pnl.
    """
    positions = _DAY_PNL_CACHE.get("pnl_rows") or _DAY_PNL_CACHE.get("positions") or []
    if not positions:
        return cached_day_pnl()

    now = time.time()
    last_quote = float(_DAY_PNL_CACHE.get("hybrid_ltp_ts") or 0)
    hybrid_ltps: dict[str, float] = dict(_DAY_PNL_CACHE.get("hybrid_ltps") or {})

    open_syms = [
        str(p.get("symbol") or "")
        for p in positions
        if (p.get("qty") or 0) != 0 and str(p.get("symbol") or "")
    ]
    need_quote = bool(open_syms) and (force or (now - last_quote) >= _HYBRID_LTP_MIN_INTERVAL_S)
    if need_quote and broker is not None:
        getter = getattr(broker, "get_ltps_kite_batch", None)
        if callable(getter):
            try:
                fresh = getter(open_syms)
                if isinstance(fresh, dict) and fresh:
                    hybrid_ltps.update({str(k): float(v) for k, v in fresh.items() if v})
                    _DAY_PNL_CACHE["hybrid_ltps"] = hybrid_ltps
                    _DAY_PNL_CACHE["hybrid_ltp_ts"] = now
            except Exception:
                pass

    # Update LTP only — do not rewrite row pnl (broker is source of truth).
    for row in positions:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "")
        ltp_ov = hybrid_ltps.get(sym)
        if ltp_ov is not None and float(row.get("qty") or 0) != 0:
            row["ltp"] = float(ltp_ov)

    display = _DAY_PNL_CACHE.get("positions")
    if isinstance(display, list) and display is not positions:
        for row in display:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "")
            ltp_ov = hybrid_ltps.get(sym)
            if ltp_ov is not None and float(row.get("qty") or 0) != 0:
                row["ltp"] = float(ltp_ov)

    broker = cached_broker_day_pnl()
    if broker is not None:
        _DAY_PNL_CACHE["hybrid_pnl"] = broker
        _DAY_PNL_CACHE["pnl"] = broker
        _DAY_PNL_CACHE["hybrid_ts"] = now
        return broker
    return cached_day_pnl()


def cached_broker_day_pnl() -> float | None:
    """Broker-reported day PnL from last get_positions (may be stale)."""
    v = _DAY_PNL_CACHE.get("broker_pnl")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _today_ist() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


def _session_path() -> Path:
    try:
        from core.batman_mode import shared_data_dir

        return shared_data_dir() / "day_pnl_session.json"
    except Exception:
        return Path("/home/ubuntu/Trading_Runtime_Rahul/Data/data/shared/day_pnl_session.json")


def _raw_day_pnl() -> float | None:
    v = _DAY_PNL_CACHE.get("hybrid_pnl")
    if v is None:
        v = _DAY_PNL_CACHE.get("broker_pnl")
    if v is None:
        v = _DAY_PNL_CACHE.get("pnl")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _active_baseline() -> float:
    if str(_DAY_PNL_CACHE.get("baseline_date") or "") != _today_ist():
        return 0.0
    try:
        return float(_DAY_PNL_CACHE.get("session_baseline") or 0)
    except (TypeError, ValueError):
        return 0.0


def _persist_session() -> None:
    import json

    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_baseline": _active_baseline() if str(_DAY_PNL_CACHE.get("baseline_date") or "") == _today_ist() else 0.0,
        "baseline_date": str(_DAY_PNL_CACHE.get("baseline_date") or _today_ist()),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload) + chr(10), encoding="utf-8")
    tmp.replace(path)


def _load_session() -> None:
    import json

    path = _session_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    day = str(data.get("baseline_date") or "")
    if day != _today_ist():
        _DAY_PNL_CACHE["session_baseline"] = 0.0
        _DAY_PNL_CACHE["baseline_date"] = _today_ist()
        return
    try:
        _DAY_PNL_CACHE["session_baseline"] = float(data.get("session_baseline") or 0)
    except (TypeError, ValueError):
        _DAY_PNL_CACHE["session_baseline"] = 0.0
    _DAY_PNL_CACHE["baseline_date"] = day


def reset_day_pnl_after_complete() -> float:
    """Confirm Complete: clear Home position rows; do not bookmark a Day PnL baseline."""
    _DAY_PNL_CACHE["session_baseline"] = 0.0
    _DAY_PNL_CACHE["baseline_date"] = _today_ist()
    _DAY_PNL_CACHE["positions"] = []
    _DAY_PNL_CACHE["pnl_rows"] = []
    # Keep live day number; only clear the table until next get_positions.
    try:
        _persist_session()
    except Exception:
        pass
    return 0.0


def cached_day_pnl() -> float | None:
    """Day P&L for Home: current book/hybrid value (no session baseline shift)."""
    v = _raw_day_pnl()
    if v is None:
        return None
    return round(float(v), 2)


def cached_positions() -> list[dict[str, Any]]:
    """Compact broker position rows from last get_positions(), or []."""
    v = _DAY_PNL_CACHE.get("positions")
    if not isinstance(v, list):
        return []
    return list(v)

def latch_idle_day_pnl() -> None:
    """Idle Home: no longer freezes Day PnL via a session baseline bookmark."""
    return
