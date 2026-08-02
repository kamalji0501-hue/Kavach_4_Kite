"""Optional cross-check against Tradehull option chain (when API returns data)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

logger = logging.getLogger("backtest_engine.option_chain")


def try_option_chain_cross_check(
    broker: Any,
    *,
    target_expiry: date,
    strikes: list[int],
    max_expiry_index: int = 8,
) -> dict[str, Any]:
    """Try ``broker.get_option_chain`` for each expiry index; report if API works.

    Returns a summary dict for the validation report. Does not fail the session
    when the chain API is empty (common outside market hours).
    """
    result: dict[str, Any] = {
        "attempted": True,
        "matched_expiry_index": None,
        "chain_available": False,
        "notes": [],
        "per_strike": {},
    }

    for idx in range(max_expiry_index):
        try:
            df = broker.get_option_chain(underlying="NIFTY", expiry=idx, num_strikes=40)
        except Exception as exc:
            result["notes"].append(f"expiry_index={idx}: {exc}")
            continue

        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            result["notes"].append(f"expiry_index={idx}: empty chain")
            continue

        result["chain_available"] = True
        sym_col = _pick_column(df, ("Symbol", "symbol", "TradingSymbol", "tradingSymbol"))
        if sym_col is None:
            result["notes"].append(f"expiry_index={idx}: unknown columns {list(df.columns)}")
            continue

        symbols = df[sym_col].astype(str).tolist()
        if any(str(target_expiry.year) in s and "Jun" in s for s in symbols):
            result["matched_expiry_index"] = idx
            for st in strikes:
                hit = [s for s in symbols if str(st) in s]
                result["per_strike"][st] = hit[:4]
            break

    if not result["chain_available"]:
        result["notes"].append(
            "Option chain API returned no rows — instrument master remains authoritative."
        )

    return result


def _pick_column(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None
