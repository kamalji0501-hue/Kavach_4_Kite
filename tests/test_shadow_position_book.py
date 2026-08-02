"""Shadow book merges core legs with ATO virtual fills."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.shadow.ledger_store import load_orders, save_orders, seed_from_uat_state
from backtest_engine.shadow.position_book import apply_virtual_fill, rebuild_positions


def test_apply_virtual_fill_adds_ato_leg() -> None:
    core = pd.DataFrame(
        [
            {
                "tradingSymbol": "NIFTY-Jun2026-23400-CE",
                "netQty": -130,
                "avgPrice": 173.2,
            }
        ]
    )
    out = apply_virtual_fill(
        core,
        symbol="NIFTY-Jun2026-23450-CE",
        qty=65,
        side="BUY",
        avg_price=185.5,
        expiry_date=date(2026, 6, 9),
    )
    assert len(out) == 2
    ato = out[out["tradingSymbol"] == "NIFTY-Jun2026-23450-CE"].iloc[0]
    assert int(ato["netQty"]) == 65


def test_rebuild_positions_from_orders() -> None:
    core = pd.DataFrame(
        [{"tradingSymbol": "NIFTY-Jun2026-23400-CE", "netQty": -130, "avgPrice": 173.2}]
    )
    orders = [
        {
            "order_id": "SHADOW-00001",
            "symbol": "NIFTY-Jun2026-23450-CE",
            "qty": 65,
            "side": "BUY",
            "status": "TRADED",
            "avg_price": 180.0,
        }
    ]
    out = rebuild_positions(core, orders, expiry_date=date(2026, 6, 9))
    assert len(out) == 2


def test_ledger_roundtrip_and_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BATMAN_MODE", "uat")
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "batman_mode.json").write_text('{"mode": "uat"}', encoding="utf-8")
    orders = [
        {
            "order_id": "SHADOW-00001",
            "symbol": "NIFTY-Jun2026-23450-CE",
            "qty": 65,
            "side": "BUY",
            "status": "TRADED",
            "avg_price": 190.0,
        }
    ]
    save_orders(tmp_path, orders)
    loaded = load_orders(tmp_path)
    assert loaded[0]["order_id"] == "SHADOW-00001"

    from core.batman_mode import shadow_ledger_path, state_path

    state_file = state_path(tmp_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "ato": {
                    "ce_ato_active": True,
                    "ce_order_id": "SHADOW-00001",
                    "ce_ato_exit_order_id": "SHADOW-00004",
                    "ce_protect_symbol": "NIFTY-Jun2026-23450-CE",
                    "pe_ato_active": True,
                    "pe_order_id": "SHADOW-00002",
                    "pe_protect_symbol": "NIFTY-Jun2026-23400-PE",
                },
                "positions": {"ce_buy": {"qty": 65}, "pe_buy": {"qty": 65}},
            }
        ),
        encoding="utf-8",
    )
    shadow_ledger_path(tmp_path).unlink(missing_ok=True)
    seeded = seed_from_uat_state(tmp_path)
    assert len(seeded) == 2
    assert {o["side"] for o in seeded} == {"BUY"}
