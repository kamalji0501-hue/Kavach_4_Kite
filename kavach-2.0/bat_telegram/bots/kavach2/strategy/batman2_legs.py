"""Batman 2.0 eight-leg strike/qty plan from an operator NIFTY center level."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LegPlan:
    """One planned NFO leg (pre-symbol resolution)."""

    key: str
    option_type: str  # CE | PE
    side: str  # BUY | SELL
    strike: int
    qty: int
    role: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Place buys (core + hedges) before sell on each side — never naked sell.
PLACE_SEQUENCE: tuple[str, ...] = (
    "ce_buy",
    "ce_margin_hedge",
    "ce_dyn_hedge",
    "ce_sell",
    "pe_buy",
    "pe_margin_hedge",
    "pe_dyn_hedge",
    "pe_sell",
)


def snap_strike(level: float, step: int = 50) -> int:
    """Round *level* to nearest NIFTY strike step (half-up)."""
    if step <= 0:
        raise ValueError(f"strike step must be positive, got {step}")
    return int(math.floor(float(level) / step + 0.5) * step)


def dyn_hedge_qty(buy_qty: int, *, lot_size: int, pct: float = 0.30) -> int:
    """30% of buy qty, rounded **down** to whole lots (0 if less than 1 lot)."""
    if buy_qty <= 0 or lot_size <= 0:
        return 0
    raw = int(buy_qty * float(pct))
    lots = raw // lot_size
    return lots * lot_size


def build_batman2_plan(
    center_level: float,
    *,
    base_lots: int = 1,
    lot_size: int = 65,
    buy_offset: int = 250,
    sell_offset: int = 300,
    dyn_from_sell: int = 200,
    margin_offset: int = 1000,
    dyn_hedge_pct: float = 0.30,
    strike_step: int = 50,
) -> list[LegPlan]:
    """Build the 8-leg Batman 2.0 plan from operator center *center_level*.

    CE: buy L+250, sell L+300 (2×), dyn L+500 (30%), margin L+1000.
    PE: buy L−250, sell L−300 (2×), dyn L−500 (30%), margin L−1000.
    """
    if base_lots < 1:
        raise ValueError(f"base_lots must be >= 1, got {base_lots}")
    if lot_size < 1:
        raise ValueError(f"lot_size must be >= 1, got {lot_size}")

    L = float(center_level)
    Q = int(base_lots) * int(lot_size)
    sell_q = 2 * Q
    dyn_q = dyn_hedge_qty(Q, lot_size=lot_size, pct=dyn_hedge_pct)

    ce_buy = snap_strike(L + buy_offset, strike_step)
    ce_sell = snap_strike(L + sell_offset, strike_step)
    ce_dyn = snap_strike(ce_sell + dyn_from_sell, strike_step)
    ce_margin = snap_strike(L + margin_offset, strike_step)

    pe_buy = snap_strike(L - buy_offset, strike_step)
    pe_sell = snap_strike(L - sell_offset, strike_step)
    pe_dyn = snap_strike(pe_sell - dyn_from_sell, strike_step)
    pe_margin = snap_strike(L - margin_offset, strike_step)

    by_key = {
        "ce_buy": LegPlan("ce_buy", "CE", "BUY", ce_buy, Q, "core_buy"),
        "ce_sell": LegPlan("ce_sell", "CE", "SELL", ce_sell, sell_q, "core_sell"),
        "ce_dyn_hedge": LegPlan(
            "ce_dyn_hedge", "CE", "BUY", ce_dyn, dyn_q, "dyn_hedge"
        ),
        "ce_margin_hedge": LegPlan(
            "ce_margin_hedge", "CE", "BUY", ce_margin, Q, "margin_hedge"
        ),
        "pe_buy": LegPlan("pe_buy", "PE", "BUY", pe_buy, Q, "core_buy"),
        "pe_sell": LegPlan("pe_sell", "PE", "SELL", pe_sell, sell_q, "core_sell"),
        "pe_dyn_hedge": LegPlan(
            "pe_dyn_hedge", "PE", "BUY", pe_dyn, dyn_q, "dyn_hedge"
        ),
        "pe_margin_hedge": LegPlan(
            "pe_margin_hedge", "PE", "BUY", pe_margin, Q, "margin_hedge"
        ),
    }
    return [by_key[k] for k in PLACE_SEQUENCE]


def plan_to_preview_rows(legs: list[LegPlan]) -> list[dict[str, Any]]:
    """Compact rows for Telegram preview."""
    return [
        {
            "key": leg.key,
            "side": leg.side,
            "type": leg.option_type,
            "strike": leg.strike,
            "qty": leg.qty,
            "role": leg.role,
        }
        for leg in legs
        if leg.qty > 0
    ]
