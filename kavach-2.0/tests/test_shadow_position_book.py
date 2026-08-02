"""Shadow book merges core legs with ATO virtual fills."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

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
    rr = tmp_path / "Batman-Runtime"
    monkeypatch.setenv("BATMAN_RUNTIME_ROOT", str(rr))
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

    state_file = rr / "data" / "uat" / "batman_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "ato": {
                    "ce_ato_active": True,
                    "ce_order_id": "SHADOW-00001",
                    "ce_ato_exit_order_id": "SHADOW-00004",
                    "ce_protect_symbol": "NIFTY-Jun2026-23450-CE",
                },
                "positions": {"ce_buy": {"qty": 65}},
            }
        ),
        encoding="utf-8",
    )
    ledger_file = rr / "data" / "uat" / "shadow_order_ledger.json"
    ledger_file.unlink(missing_ok=True)
    seeded = seed_from_uat_state(tmp_path)
    assert len(seeded) == 1
    assert seeded[0]["side"] == "BUY"
    assert seeded[0]["order_id"] == "SHADOW-00001"

    # Completed cycle (exit id only, not active) must not seed a ghost short.
    ledger_file.unlink(missing_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "ato": {
                    "ce_ato_active": False,
                    "ce_order_id": None,
                    "ce_ato_exit_order_id": "SHADOW-00004",
                    "ce_protect_symbol": "NIFTY-Jun2026-23450-CE",
                },
                "positions": {"ce_buy": {"qty": 65}},
            }
        ),
        encoding="utf-8",
    )
    assert seed_from_uat_state(tmp_path) == []
