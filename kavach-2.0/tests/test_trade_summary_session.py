"""ATO summary is Register→Complete session scoped, not calendar-day only."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

from web import trade_summary as ts


def test_closed_rows_include_prior_days_same_deployment(tmp_path: Path) -> None:
    ledger = tmp_path / "ato_trade_ledger.csv"
    fields = [
        "date_ist",
        "deployment_file",
        "side",
        "buy_order_id",
        "sell_order_id",
        "buy_option_premium",
        "sell_option_premium",
        "protect_symbol",
        "protect_strike",
        "qty",
        "lots",
        "buy_timestamp_ist",
        "sell_timestamp_ist",
        "buy_nifty_ltp",
        "sell_nifty_ltp",
        "entry_trigger_level",
        "exit_trigger_level",
        "cycle_index",
    ]
    rows = [
        {
            "date_ist": "2026-09-10",
            "deployment_file": "batman_sessionA.json",
            "side": "CE",
            "buy_order_id": "1",
            "sell_order_id": "2",
            "buy_option_premium": "40",
            "sell_option_premium": "30",
            "protect_symbol": "NIFTY25SEP25000CE",
            "protect_strike": "25000",
            "qty": "650",
            "lots": "10",
            "buy_timestamp_ist": "2026-09-10 10:00:00 IST",
            "sell_timestamp_ist": "2026-09-10 11:00:00 IST",
            "buy_nifty_ltp": "25000",
            "sell_nifty_ltp": "24950",
            "entry_trigger_level": "25000",
            "exit_trigger_level": "24950",
            "cycle_index": "1",
        },
        {
            "date_ist": "2026-09-11",
            "deployment_file": "batman_sessionA.json",
            "side": "PE",
            "buy_order_id": "3",
            "sell_order_id": "4",
            "buy_option_premium": "20",
            "sell_option_premium": "25",
            "protect_symbol": "NIFTY25SEP24500PE",
            "protect_strike": "24500",
            "qty": "650",
            "lots": "10",
            "buy_timestamp_ist": "2026-09-11 10:00:00 IST",
            "sell_timestamp_ist": "2026-09-11 11:00:00 IST",
            "buy_nifty_ltp": "24500",
            "sell_nifty_ltp": "24450",
            "entry_trigger_level": "24500",
            "exit_trigger_level": "24450",
            "cycle_index": "2",
        },
        {
            "date_ist": "2026-09-11",
            "deployment_file": "batman_other.json",
            "side": "CE",
            "buy_order_id": "5",
            "sell_order_id": "6",
            "buy_option_premium": "10",
            "sell_option_premium": "12",
            "protect_symbol": "NIFTY25SEP25100CE",
            "protect_strike": "25100",
            "qty": "65",
            "lots": "1",
            "buy_timestamp_ist": "2026-09-11 12:00:00 IST",
            "sell_timestamp_ist": "2026-09-11 13:00:00 IST",
            "buy_nifty_ltp": "25100",
            "sell_nifty_ltp": "25050",
            "entry_trigger_level": "25100",
            "exit_trigger_level": "25050",
            "cycle_index": "1",
        },
    ]
    with ledger.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    with patch.object(ts, "_ledger_path", return_value=ledger):
        with patch.object(ts, "_broker_fill_map", return_value={}):
            closed = ts._closed_rows_for_session("batman_sessionA.json")
    assert len(closed) == 2
    assert closed[0]["session_cycle"] == 1
    assert closed[1]["session_cycle"] == 2
    assert closed[0]["date_ist"] == "2026-09-10"
    assert closed[1]["date_ist"] == "2026-09-11"


def test_trade_summary_empty_without_deployment() -> None:
    class _St:
        def get(self, k, default=None):
            return False if "confirmed" in k else default

    with patch.object(ts, "_runtime_state", return_value=_St()):
        out = ts.trade_summary()
    assert out["closed"] == []
    assert out["count"] == 0
    assert out["session_deployment"] is None
