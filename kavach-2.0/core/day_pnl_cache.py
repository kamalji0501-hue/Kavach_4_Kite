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
        _DAY_PNL_CACHE["pnl"] = round(float(pnl), 2)
        _DAY_PNL_CACHE["ts"] = time.time()
        # Positions list from net (preferred); fall back to day if net missing.
        src = net if net else rows
        _DAY_PNL_CACHE["positions"] = _select_rows(src)
    except Exception:
        pass


def cached_day_pnl() -> float | None:
    """Last day P&L from a positions REST response, or None if never fetched."""
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
