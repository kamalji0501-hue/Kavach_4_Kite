"""
Batman v3 — Typed domain models.

These dataclasses form the shared data contract used across both batman_v3
(strategy / Telegram layer) and the Sapient LTP fetcher (data acquisition).

Keeping the same model definitions in both codebases means the eventual
merge is a straight import-path swap with zero logic rewriting.

  batman_v3/core/models.py      ←─ canonical source
  Sapient/app/domain/models.py  ←─ mirrors this; replaced by import on merge
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ── Market data ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LTPQuote:
    """Last traded price for a single instrument."""

    symbol: str
    ltp: float
    timestamp: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        return f"{self.symbol} ₹{self.ltp:,.2f}" f" @ {self.timestamp.strftime('%H:%M:%S')}"


# ── Positions ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LegPosition:
    """One leg of an iron condor or ATO order.

    ``qty`` is negative for short/sell legs, positive for long/buy legs.
    """

    symbol: str
    qty: int
    order_id: str
    avg_price: float
    side: str  # "CE" | "PE"
    leg_type: str  # "sell" | "buy"

    @property
    def is_short(self) -> bool:
        return self.qty < 0

    @property
    def notional(self) -> float:
        """Notional value = abs(qty) × avg_price."""
        return abs(self.qty) * self.avg_price


@dataclass
class IronCondorPosition:
    """Full 4-leg iron condor position."""

    ce_sell: LegPosition
    ce_buy: LegPosition
    pe_sell: LegPosition
    pe_buy: LegPosition

    @property
    def is_complete(self) -> bool:
        return all((self.ce_sell, self.ce_buy, self.pe_sell, self.pe_buy))

    @property
    def net_premium(self) -> float:
        """Premium received (sell legs) minus premium paid (buy legs)."""
        received = (
            abs(self.ce_sell.qty) * self.ce_sell.avg_price
            + abs(self.pe_sell.qty) * self.pe_sell.avg_price
        )
        paid = (
            abs(self.ce_buy.qty) * self.ce_buy.avg_price
            + abs(self.pe_buy.qty) * self.pe_buy.avg_price
        )
        return received - paid


# ── Orders ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrderResult:
    """Outcome of a single broker order placement."""

    order_id: str
    symbol: str
    transaction_type: str  # "BUY" | "SELL"
    qty: int
    avg_price: float
    status: str  # "TRADED" | "PENDING" | "REJECTED" | "CANCELLED"

    @property
    def is_filled(self) -> bool:
        return self.status == "TRADED"
