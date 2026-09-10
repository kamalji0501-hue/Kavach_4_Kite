"""Local-book validation for ATO fills (lot multiples of 65)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def net_qty_for_symbol(
    broker: Any,
    symbol: str,
    *,
    position_reader: Callable[[], Any] | None = None,
) -> int | None:
    """Return net long qty for symbol, or None if book unreadable."""
    try:
        if position_reader is not None:
            positions = position_reader()
        else:
            positions = broker.get_positions()
        if positions is None:
            return None
        if hasattr(positions, "empty") and positions.empty:
            return 0
        if hasattr(positions, "iterrows"):
            for _, row in positions.iterrows():
                sym = row.get("tradingSymbol") or row.get("tradingsymbol", "")
                if sym == symbol:
                    net = row.get("netQty", 0)
                    if net is None or net == "":
                        buy_q = int(row.get("buyQty", 0) or 0)
                        sell_q = int(row.get("sellQty", 0) or 0)
                        net = buy_q - sell_q
                    return int(net)
            return 0
        if isinstance(positions, list):
            for row in positions:
                sym = row.get("tradingSymbol") or row.get("tradingsymbol", "")
                if sym == symbol:
                    return int(row.get("netQty", 0) or 0)
            return 0
    except Exception:
        return None
    return None


def qty_to_whole_lots(qty: int, lot_size: int) -> int:
    if lot_size <= 0:
        return 0
    return abs(int(qty)) // lot_size


def lots_fulfilled(actual_qty: int, expected_qty: int, lot_size: int) -> bool:
    """True when book has at least the expected long qty (overfill counts as done)."""
    if expected_qty <= 0:
        return actual_qty <= 0
    # Lot-aware: enough whole lots, and never treat overfill as a miss.
    if lot_size > 0:
        return qty_to_whole_lots(actual_qty, lot_size) >= qty_to_whole_lots(
            expected_qty, lot_size
        )
    return int(actual_qty) >= int(expected_qty)


def remainder_lots(actual_qty: int, expected_qty: int, lot_size: int) -> int:
    """Whole lots still missing (0 if fulfilled / overfilled)."""
    exp_lots = qty_to_whole_lots(expected_qty, lot_size)
    act_lots = qty_to_whole_lots(actual_qty, lot_size)
    return max(0, exp_lots - act_lots)


def remainder_qty(actual_qty: int, expected_qty: int, lot_size: int) -> int:
    """Qty still missing in lot multiples (0 if fulfilled / overfilled)."""
    missing = remainder_lots(actual_qty, expected_qty, lot_size)
    if missing <= 0 or lot_size <= 0:
        return 0
    return int(missing) * int(lot_size)
