"""Aggressive LIMIT pricing helpers (SEBI/algo-safe market emulation).

Algo APIs must not send unconstrained MARKET orders. Platforms emulate
fills with LIMIT priced through the book: BUY above LTP, SELL below LTP,
snapped to the instrument tick.
"""

from __future__ import annotations

import math
from typing import Literal

# NSE index options commonly trade in ₹0.05 ticks (Dhan master TICK_SIZE=5.0 paise).
DEFAULT_OPTION_TICK = 0.05
DEFAULT_LIMIT_BUFFER_PCT = 10.0


def round_to_tick(
    price: float,
    tick: float = DEFAULT_OPTION_TICK,
    *,
    side: Literal["BUY", "SELL"] | None = None,
) -> float:
    """Snap ``price`` to ``tick``.

    BUY uses ceil (more aggressive), SELL uses floor. When ``side`` is None,
    round to nearest tick.
    """
    if tick <= 0:
        raise ValueError(f"tick must be positive, got {tick}")
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")

    units = price / tick
    if side == "BUY":
        snapped = math.ceil(units - 1e-12) * tick
    elif side == "SELL":
        snapped = math.floor(units + 1e-12) * tick
    else:
        snapped = round(units) * tick

    # Never round a SELL to zero; bump one tick if floor collapsed.
    if snapped <= 0:
        snapped = tick
    return round(snapped, 10)


def aggressive_limit_price(
    ltp: float,
    side: Literal["BUY", "SELL"] | str,
    *,
    buffer_pct: float = DEFAULT_LIMIT_BUFFER_PCT,
    tick: float = DEFAULT_OPTION_TICK,
) -> float:
    """Return LIMIT price that behaves like a marketable order.

    BUY  → LTP × (1 + buffer_pct/100), ceil to tick
    SELL → LTP × (1 − buffer_pct/100), floor to tick
    """
    if ltp <= 0:
        raise ValueError(f"ltp must be positive, got {ltp}")
    if buffer_pct < 0:
        raise ValueError(f"buffer_pct must be >= 0, got {buffer_pct}")

    side_u = str(side).upper()
    if side_u not in {"BUY", "SELL"}:
        raise ValueError(f"side must be BUY or SELL, got {side}")

    factor = 1.0 + (buffer_pct / 100.0) if side_u == "BUY" else 1.0 - (buffer_pct / 100.0)
    raw = ltp * factor
    if raw <= 0:
        raw = tick
    return round_to_tick(raw, tick, side=side_u)  # type: ignore[arg-type]
