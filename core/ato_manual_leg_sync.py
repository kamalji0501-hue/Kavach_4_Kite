"""Mid-session manual Dhan leg sync (KAVACH operator bible §7).

Wrong-strike / stray broker legs (Q50) are never acted on — only the registered
protect symbol for each side is evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Side = Literal["CE", "PE"]


@dataclass(frozen=True)
class ManualLegSyncResult:
    """Outcome for one side on a poll tick."""

    action: str
    side: Side
    symbol: str = ""
    broker_qty: int = 0
    expected_qty: int = 0


def symbol_qty_map(broker_df: Any) -> dict[str, int] | None:
    """Build symbol → signed net qty map (long +, short −); None if unreadable.

    ATO entry treats qty > 0 as “protect already long”. Short phantoms must not
    block re-entry (abs() previously did).
    """
    if broker_df is None:
        return None
    try:
        if hasattr(broker_df, "empty") and broker_df.empty:
            return {}
        if hasattr(broker_df, "iterrows"):
            out: dict[str, int] = {}
            for _, row in broker_df.iterrows():
                sym = row.get("tradingSymbol") or row.get("tradingsymbol", "")
                if not sym:
                    continue
                net = row.get("netQty", 0)
                if net is None or net == "":
                    buy_q = int(row.get("buyQty", 0) or 0)
                    sell_q = int(row.get("sellQty", 0) or 0)
                    net = buy_q - sell_q
                out[str(sym)] = int(net)
            return out
        if isinstance(broker_df, list):
            out = {}
            for row in broker_df:
                sym = row.get("tradingSymbol") or row.get("tradingsymbol", "")
                if sym:
                    out[str(sym)] = int(row.get("netQty", 0) or 0)
            return out
    except Exception:
        return None
    return None


def evaluate_side_manual_sync(
    *,
    side: Side,
    protect_symbol: str | None,
    expected_qty: int,
    triggered: bool,
    ato_active: bool,
    broker_qty: int | None,
    side_halted: bool,
    protect_seen_at_broker: bool = False,
    lot_size: int = 65,
    manual_protect_adopt_enabled: bool = True,
) -> ManualLegSyncResult | None:
    """Return a sync action for one side, or None when no action needed."""
    if side_halted or not protect_symbol or expected_qty <= 0:
        return None
    if broker_qty is None:
        return None

    symbol = str(protect_symbol)

    # 26A — idle; manual buy at registered protect strike → adopt (exit-only)
    if manual_protect_adopt_enabled and not triggered and broker_qty > 0:
        return ManualLegSyncResult(
            action="adopt_idle",
            side=side,
            symbol=symbol,
            broker_qty=broker_qty,
            expected_qty=expected_qty,
        )

    # 26D / 31 — holding; operator manually changed registered protect qty
    if ato_active and protect_seen_at_broker:
        if broker_qty == 0:
            return ManualLegSyncResult(
                action="pause_full_exit",
                side=side,
                symbol=symbol,
                broker_qty=0,
                expected_qty=expected_qty,
            )
        if lot_size > 0 and broker_qty % lot_size != 0:
            return None
        if 0 < broker_qty < expected_qty:
            return ManualLegSyncResult(
                action="pause_partial_exit",
                side=side,
                symbol=symbol,
                broker_qty=broker_qty,
                expected_qty=expected_qty,
            )

    return None
