"""MAIN_ORDER_BROKER selector — default zerodha; UAT stays ShadowBroker."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.batman_mode import get_mode, is_uat
from core.broker_factory import create_broker
from core.order_broker_select import (
    get_main_order_broker,
    normalize_main_broker,
    set_main_order_broker,
)


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


def test_normalize_aliases() -> None:
    assert normalize_main_broker("kite") == "zerodha"
    assert normalize_main_broker("Z") == "zerodha"
    assert normalize_main_broker("dhanhq") == "dhan"
    assert normalize_main_broker("tradehull") == "dhan"
    assert normalize_main_broker("nope") == ""


def test_default_main_order_broker_is_zerodha(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MAIN_ORDER_BROKER", raising=False)
    # secrets_root → Trading_Runtime under workspace; point batman mode runtime
    _write_mode_config(tmp_path, "prod")
    assert get_main_order_broker(tmp_path) == "zerodha"


def test_set_main_order_broker_writes_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MAIN_ORDER_BROKER", raising=False)
    _write_mode_config(tmp_path, "prod")
    # secrets live under secrets_root(tmp_path); create layout via batman_mode
    from core.batman_mode import secrets_root

    secrets_root(tmp_path).mkdir(parents=True, exist_ok=True)
    got = set_main_order_broker("dhan", tmp_path)
    assert got == "dhan"
    assert get_main_order_broker(tmp_path) == "dhan"
    env_file = secrets_root(tmp_path) / "config" / "order_broker.env"
    assert env_file.is_file()
    assert "MAIN_ORDER_BROKER=dhan" in env_file.read_text(encoding="utf-8")


def test_uat_shadow_ignores_main_picker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MAIN_ORDER_BROKER", "dhan")
    _write_mode_config(tmp_path, "uat")
    assert get_mode(tmp_path) == "uat"
    assert is_uat(tmp_path)
    shadow_mock = MagicMock(name="ShadowBroker")
    with patch(
        "backtest_engine.shadow.shadow_broker.ShadowBroker.connect_with_token",
        return_value=shadow_mock,
    ) as connect:
        broker = create_broker("CLIENT", "token", root=tmp_path)
    connect.assert_called_once()
    assert broker is shadow_mock
