"""Merge Sensibull core book with virtual shadow order fills."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def _parse_strike_from_symbol(symbol: str) -> tuple[int, str]:
    import re

    sym = str(symbol).strip()
    m = re.search(r"-(\d{4,5})-(CE|PE)$", sym, re.I)
    if m:
        return int(m.group(1)), m.group(2).upper()
    m = re.search(r"(\d{4,5})(CE|PE)$", sym.replace("-", ""), re.I)
    if m:
        return int(m.group(1)), m.group(2).upper()
    return 0, ""


def _resolve_broker_row(
    symbol: str,
    net_qty: int,
    avg_price: float = 0.0,
    *,
    expiry_date: date | None = None,
    master: pd.DataFrame | None = None,
) -> dict[str, Any]:
    from backtest_engine.resolver.instrument_master import load_instrument_master, resolve_nifty_option

    strike, opt = _parse_strike_from_symbol(symbol)
    row: dict[str, Any] = {
        "tradingSymbol": symbol,
        "netQty": net_qty,
        "avgPrice": avg_price,
        "costPrice": avg_price,
        "exchangeSegment": "NSE_FNO",
        "productType": "MARGIN",
        "drvStrikePrice": float(strike) if strike else 0.0,
        "drvOptionType": opt,
    }
    if strike and opt and expiry_date:
        try:
            if master is None:
                master = load_instrument_master()
            inst = resolve_nifty_option(
                strike=strike, option_type=opt, expiry_date=expiry_date, master=master
            )
            row = inst.to_broker_row(net_qty=net_qty, avg_price=avg_price)
        except Exception:
            pass
    return row


def apply_virtual_fill(
    positions_df: pd.DataFrame,
    *,
    symbol: str,
    qty: int,
    side: str,
    avg_price: float = 0.0,
    expiry_date: date | None = None,
    master: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Apply one TRADED shadow order onto a positions DataFrame."""
    sym_col = "tradingSymbol"
    df = positions_df.copy() if positions_df is not None else pd.DataFrame()
    delta = int(qty) if str(side).upper() == "BUY" else -int(qty)

    if df.empty or sym_col not in df.columns:
        return pd.DataFrame(
            [_resolve_broker_row(symbol, delta, avg_price, expiry_date=expiry_date, master=master)]
        )

    mask = df[sym_col].astype(str) == symbol
    if mask.any():
        idx = df.index[mask][0]
        cur = int(df.at[idx, "netQty"])
        new_qty = cur + delta
        if new_qty == 0:
            return df.drop(index=idx).reset_index(drop=True)
        df.at[idx, "netQty"] = new_qty
        return df

    new_row = _resolve_broker_row(
        symbol, delta, avg_price, expiry_date=expiry_date, master=master
    )
    return pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)


def rebuild_positions(
    core_df: pd.DataFrame,
    orders: list[dict[str, Any]],
    *,
    expiry_date: date | None = None,
    master: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Core Sensibull legs + all TRADED virtual orders (ATO protect, etc.)."""
    from backtest_engine.resolver.instrument_master import load_instrument_master

    df = core_df.copy() if core_df is not None else pd.DataFrame()
    # Load once for the whole rebuild — ledger can have hundreds of TRADED fills.
    if master is None and expiry_date is not None:
        needs_resolve = any(
            str(o.get("status", "")).upper() == "TRADED" for o in orders
        )
        if needs_resolve:
            master = load_instrument_master()
    for order in orders:
        if str(order.get("status", "")).upper() != "TRADED":
            continue
        df = apply_virtual_fill(
            df,
            symbol=str(order["symbol"]),
            qty=int(order["qty"]),
            side=str(order.get("side") or order.get("transaction_type") or "BUY"),
            avg_price=float(order.get("avg_price") or 0.0),
            expiry_date=expiry_date,
            master=master,
        )
    return df
