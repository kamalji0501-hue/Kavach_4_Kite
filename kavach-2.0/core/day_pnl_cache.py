"""Shared day P&L + positions cache for Kavach Home.

Updated only when get_positions() already hits Kite (no extra REST).
Uses a sys.modules singleton so parent/core and kavach-2.0/core share one cache
even if both zerodha_broker copies are imported.
"""

from __future__ import annotations

import sys
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
    return {
        "symbol": str(r.get("tradingsymbol") or r.get("symbol") or ""),
        "exchange": str(r.get("exchange") or ""),
        "product": str(r.get("product") or ""),
        "qty": qty,
        "avg": avg,
        "ltp": ltp,
        "pnl": pnl,
        "unrealised": unrealised,
        "realised": realised,
    }


def _select_rows(net: Any) -> list[dict[str, Any]]:
    raw = list(net or []) if isinstance(net, list) else []
    compact: list[dict[str, Any]] = []
    for r in raw:
        c = _compact_row(r)
        if c is not None:
            compact.append(c)
    open_rows = [c for c in compact if (c.get("qty") or 0) != 0]
    if open_rows:
        return open_rows
    # Prefer useful day-closed / flat rows: non-zero pnl or qty.
    useful = [
        c
        for c in compact
        if (c.get("qty") or 0) != 0
        or (c.get("pnl") is not None and float(c.get("pnl") or 0) != 0)
    ]
    return useful if useful else compact


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
        # All legs with open qty or non-zero day pnl (incl. closed) for hybrid MTM.
        _DAY_PNL_CACHE["pnl_rows"] = [
            c
            for c in compact
            if (c.get("qty") or 0) != 0
            or (c.get("pnl") is not None and float(c.get("pnl") or 0) != 0)
        ] or compact
    except Exception:
        pass



_HYBRID_LTP_MIN_INTERVAL_S = 1.0


def _leg_hybrid_pnl(row: dict[str, Any], *, ltp_override: float | None) -> float:
    qty = float(row.get("qty") or 0)
    broker_pnl = _f(row, "pnl")
    if broker_pnl is None:
        broker_pnl = 0.0
    if qty == 0:
        return float(broker_pnl)
    avg = _f(row, "avg")
    if avg is None:
        return float(broker_pnl)
    unreal_broker = _f(row, "unrealised", "unrealized") or 0.0
    ltp = ltp_override if ltp_override is not None else (_f(row, "ltp") or avg)
    unreal_hybrid = (float(ltp) - float(avg)) * qty
    return float(broker_pnl) - float(unreal_broker) + float(unreal_hybrid)


def refresh_hybrid_day_pnl(*, broker: Any = None, force: bool = False) -> float | None:
    """Recompute day PnL from broker book + fresh Kite LTPs (1 batched quote / ~1s max).

    Keeps realised from the last get_positions(); replaces stale unrealised using live LTPs.
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

    total = 0.0
    for row in positions:
        sym = str(row.get("symbol") or "")
        ltp_ov = hybrid_ltps.get(sym)
        total += _leg_hybrid_pnl(row, ltp_override=ltp_ov)

    hybrid = round(float(total), 2)
    _DAY_PNL_CACHE["hybrid_pnl"] = hybrid
    _DAY_PNL_CACHE["hybrid_ts"] = now
    _DAY_PNL_CACHE["pnl"] = hybrid
    return hybrid


def cached_broker_day_pnl() -> float | None:
    """Broker-reported day PnL from last get_positions (may be stale)."""
    v = _DAY_PNL_CACHE.get("broker_pnl")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def cached_day_pnl() -> float | None:
    """Hybrid day P&L when refreshed; else broker cache from get_positions."""
    v = _DAY_PNL_CACHE.get("hybrid_pnl")
    if v is None:
        v = _DAY_PNL_CACHE.get("pnl")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cached_positions() -> list[dict[str, Any]]:
    """Compact broker position rows from last get_positions(), or []."""
    v = _DAY_PNL_CACHE.get("positions")
    if not isinstance(v, list):
        return []
    return list(v)
