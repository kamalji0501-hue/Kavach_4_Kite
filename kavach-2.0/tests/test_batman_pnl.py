from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from core.batman_pnl import (
    ato_summary_rupees_asof,
    compute_batman_pnl,
    overnight_summary_rupees_asof,
    previous_trading_day,
)


def test_previous_trading_day_skips_weekend():
    assert previous_trading_day(date(2026, 9, 14)) == date(2026, 9, 11)


def test_ato_asof_sums_through_prior_day(tmp_path: Path):
    ledger = tmp_path / "ato_trade_ledger.csv"
    fields = [
        "date_ist",
        "deployment_file",
        "buy_option_premium",
        "sell_option_premium",
        "qty",
    ]
    rows = [
        {
            "date_ist": "2026-09-16",
            "deployment_file": "batman_A.json",
            "buy_option_premium": "40",
            "sell_option_premium": "30",
            "qty": "10",
        },
        {
            "date_ist": "2026-09-17",
            "deployment_file": "batman_A.json",
            "buy_option_premium": "20",
            "sell_option_premium": "25",
            "qty": "10",
        },
        {
            "date_ist": "2026-09-18",
            "deployment_file": "batman_A.json",
            "buy_option_premium": "10",
            "sell_option_premium": "12",
            "qty": "10",
        },
    ]
    with ledger.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    assert ato_summary_rupees_asof(
        deployment_name="batman_A.json", asof=date(2026, 9, 17), ledger_path=ledger
    ) == -50.0


def test_overnight_asof_and_batman_total():
    class _S:
        def __init__(self):
            self.d = {
                "deployment.confirmed": True,
                "deployment.batman_complete": False,
                "deployment.file": "/tmp/batman_A.json",
                "overnight.cycles": [
                    {
                        "status": "closed",
                        "date_ist": "2026-09-17",
                        "impact": -2.0,
                        "impact_rupees": -200.0,
                        "qty": 100,
                    },
                    {
                        "status": "closed",
                        "date_ist": "2026-09-18",
                        "impact": 1.0,
                        "impact_rupees": 100.0,
                        "qty": 100,
                    },
                ],
            }

        def get(self, k, default=None):
            return self.d.get(k, default)

    st = _S()
    assert overnight_summary_rupees_asof(state=st, asof=date(2026, 9, 17)) == -200.0
    out = compute_batman_pnl(state=st, day_pnl=1000.0, today=date(2026, 9, 18))
    assert out["asof_date"] == "2026-09-17"
    assert out["overnight_prev_day_rupees"] == -200.0
    assert out["batman_pnl"] == 800.0
