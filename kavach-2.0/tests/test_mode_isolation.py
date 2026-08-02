"""Mode boundary contract — UAT shadow code must never run in prod."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.batman_mode import data_root, get_mode, is_uat, log_root, orders_blocked
from core.broker_factory import create_broker


def _write_mode_config(root: Path, mode: str) -> None:
    cfg = {
        "mode": mode,
        "runtime_root": str(root / "Batman-Runtime"),
        "modes": {
            "dev": {"orders": "blocked"},
            "uat": {"orders": "virtual"},
            "prod": {"orders": "live"},
        },
    }
    path = root / "config" / "batman_mode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg), encoding="utf-8")


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_non_uat_modes_use_batman_broker(mode: str, tmp_path: Path) -> None:
    _write_mode_config(tmp_path, mode)
    assert get_mode(tmp_path) == mode
    assert not is_uat(tmp_path)

    live_mock = MagicMock(name="BatmanBroker")
    with patch("core.broker.BatmanBroker.connect_with_token", return_value=live_mock) as connect:
        broker = create_broker("CLIENT", "token", root=tmp_path)

    connect.assert_called_once_with("CLIENT", "token")
    assert broker is live_mock
    assert type(broker).__name__ != "ShadowBroker"


def test_dev_blocks_orders_prod_allows(tmp_path: Path) -> None:
    _write_mode_config(tmp_path, "dev")
    assert orders_blocked(tmp_path) is True

    _write_mode_config(tmp_path, "prod")
    assert orders_blocked(tmp_path) is False


def test_mode_data_and_log_roots_are_separate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BATMAN_RUNTIME_ROOT", raising=False)
    rr = tmp_path / "Batman-Runtime"
    for mode in ("dev", "uat", "prod"):
        _write_mode_config(tmp_path, mode)
        assert data_root(tmp_path) == rr / "data" / mode
        assert log_root(tmp_path) == rr / "logs" / mode


def test_uat_mode_uses_shadow_broker(tmp_path: Path) -> None:
    _write_mode_config(tmp_path, "uat")
    shadow_mock = MagicMock(name="ShadowBroker")
    with patch(
        "backtest_engine.shadow.shadow_broker.ShadowBroker.connect_with_token",
        return_value=shadow_mock,
    ) as connect:
        broker = create_broker("CLIENT", "token", root=tmp_path)

    connect.assert_called_once()
    assert broker is shadow_mock


def test_shadow_broker_rejected_outside_uat(tmp_path: Path) -> None:
    from backtest_engine.shadow.shadow_broker import ShadowBroker

    _write_mode_config(tmp_path, "prod")
    with pytest.raises(RuntimeError, match="UAT-only"):
        ShadowBroker.connect_with_token("CLIENT", "token", workspace_root=tmp_path)


def test_prod_position_enrich_uses_shared_marketfeed_path() -> None:
    from core.uat_position_enrich import enrich_nifty_positions

    broker = type(
        "BatmanBroker",
        (),
        {
            "get_nifty_option_ltps": lambda self, legs, expiry_date=None: {
                (23450, "CE"): 155.0,
            },
        },
    )()
    positions = [
        {
            "symbol": "NIFTY-Jun2026-23450-CE",
            "strike": 23450,
            "opt_type": "CE",
            "direction": "LONG",
            "qty": 65,
            "avg_price": 0,
            "expiry": "09 Jun 2026",
        }
    ]
    out = enrich_nifty_positions(positions, fixture=None, chain_broker=broker)
    assert out[0]["avg_price"] == 155.0


def test_uat_register_cleanup_skipped_outside_uat(tmp_path: Path) -> None:
    from core.uat_register_cleanup import prepare_uat_register_fresh

    _write_mode_config(tmp_path, "prod")
    result = prepare_uat_register_fresh(tmp_path)
    assert result.get("skipped") is True
