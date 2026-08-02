"""Orphan protect leg detection at register confirm (Q40 / Q59)."""

from __future__ import annotations

from typing import Any


def _net_long_qty(row: dict[str, Any]) -> int:
    net = row.get("netQty", 0)
    if net is None or net == "":
        buy_q = int(row.get("buyQty", 0) or 0)
        sell_q = int(row.get("sellQty", 0) or 0)
        net = buy_q - sell_q
    return int(net)


def registered_symbol_set(
    selected: dict[str, dict[str, Any] | None],
    *,
    ce_protect_symbol: str | None = None,
    pe_protect_symbol: str | None = None,
) -> set[str]:
    """Symbols managed by the new registration (Batman legs + protect targets)."""
    symbols: set[str] = set()
    for leg in selected.values():
        if leg and leg.get("symbol"):
            symbols.add(str(leg["symbol"]))
    if ce_protect_symbol:
        symbols.add(str(ce_protect_symbol))
    if pe_protect_symbol:
        symbols.add(str(pe_protect_symbol))
    return symbols


def detect_orphan_long_legs(
    broker_positions: list[dict[str, Any]],
    registered_symbols: set[str],
) -> list[str]:
    """Return human-readable warnings for long NIFTY legs outside registration scope."""
    warnings: list[str] = []
    for row in broker_positions:
        sym = str(row.get("tradingSymbol") or row.get("tradingsymbol") or "")
        if not sym or "NIFTY" not in sym.upper():
            continue
        qty = _net_long_qty(row)
        if qty <= 0:
            continue
        if sym in registered_symbols:
            continue
        warnings.append(
            f"{sym} (long qty {qty}) is outside this registration — algo will ignore it"
        )
    return warnings
