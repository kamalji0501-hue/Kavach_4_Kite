#!/usr/bin/env python3
"""Export CE/PE ATO live-test Excel from ato_trade_ledger.csv.

Columns (per plan):
  Side | Entry time | Entry premium | Entry Nifty | Exit time | Exit premium | Exit Nifty
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IST = ZoneInfo("Asia/Kolkata")


def _default_ledger() -> Path:
    from core.batman_mode import data_root

    return data_root(ROOT) / "analytics" / "ato" / "ato_trade_ledger.csv"


def _default_out(day: str) -> Path:
    from core.batman_mode import data_root

    out_dir = data_root(ROOT) / "analytics" / "ato" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"ato_live_test_{day}.xlsx"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export ATO live-test Excel")
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--date",
        default=datetime.now(IST).strftime("%Y-%m-%d"),
        help="IST calendar date YYYY-MM-DD (default: today IST)",
    )
    args = parser.parse_args()

    try:
        import pandas as pd
    except ImportError:
        print("FAIL: pandas required", file=sys.stderr)
        return 1

    ledger = args.ledger or _default_ledger()
    if not ledger.is_file():
        print(f"FAIL: ledger missing: {ledger}", file=sys.stderr)
        return 1

    df = pd.read_csv(ledger)
    if df.empty:
        print(f"FAIL: ledger empty: {ledger}", file=sys.stderr)
        return 1

    # Prefer date_ist; fall back to buy timestamp prefix
    if "date_ist" in df.columns:
        day_mask = df["date_ist"].astype(str).str.startswith(args.date)
    else:
        day_mask = df["buy_timestamp_ist"].astype(str).str.startswith(args.date)
    day = df.loc[day_mask].copy()
    if day.empty:
        print(f"FAIL: no rows for date={args.date} in {ledger}", file=sys.stderr)
        return 1

    # Completed cycles only (need both buy + sell)
    if "sell_timestamp_ist" in day.columns:
        day = day[day["sell_timestamp_ist"].notna() & (day["sell_timestamp_ist"].astype(str).str.len() > 0)]
    if day.empty:
        print(f"FAIL: no completed cycles for date={args.date}", file=sys.stderr)
        return 1

    out_df = pd.DataFrame(
        {
            "Side": day.get("side", ""),
            "Entry time (IST)": day.get("buy_timestamp_ist", ""),
            "Entry premium": day.get("buy_option_premium", ""),
            "Entry Nifty": day.get("buy_nifty_ltp", ""),
            "Exit time (IST)": day.get("sell_timestamp_ist", ""),
            "Exit premium": day.get("sell_option_premium", ""),
            "Exit Nifty": day.get("sell_nifty_ltp", ""),
            "Protect strike": day.get("protect_strike", ""),
            "Lots": day.get("lots", ""),
            "Premium PnL": day.get("premium_pnl", ""),
        }
    )
    # CE then PE, then time
    side_order = {"CE": 0, "PE": 1}
    out_df["_ord"] = out_df["Side"].map(lambda s: side_order.get(str(s).upper(), 9))
    out_df = out_df.sort_values(["_ord", "Entry time (IST)"]).drop(columns=["_ord"])

    out = args.out or _default_out(args.date.replace("-", ""))
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        out_df.to_excel(writer, sheet_name="ATO_CE_PE", index=False)
        summary = pd.DataFrame(
            [
                {"metric": "date_ist", "value": args.date},
                {"metric": "cycles", "value": len(out_df)},
                {"metric": "ce_cycles", "value": int((out_df["Side"].astype(str).str.upper() == "CE").sum())},
                {"metric": "pe_cycles", "value": int((out_df["Side"].astype(str).str.upper() == "PE").sum())},
                {"metric": "source_ledger", "value": str(ledger)},
            ]
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)

    print(f"OK: wrote {out} ({len(out_df)} cycles)")
    print(out_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
