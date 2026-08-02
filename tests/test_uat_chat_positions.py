"""UAT cursor_chat positions — chat screenshot path (8-leg book)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.uat_chat_positions import (
    UATChatPositionsError,
    build_fixture,
    is_cursor_chat_positions,
    validate_fixture,
)
from core.uat_ingest import ingest_uat_for_register


def _eight_legs() -> list[dict]:
    """6 BUY + 2 SELL; Core BUY not pre-marked (optional role_hint on sells only)."""
    return [
        {"role_hint": "pe_sell", "strike": 23600, "type": "PE", "side": "SELL", "lots": 14, "avg_price": 28.9},
        {"strike": 23000, "type": "PE", "side": "BUY", "lots": 7, "avg_price": 4.45},
        {"strike": 23200, "type": "PE", "side": "BUY", "lots": 7, "avg_price": 6.1},
        {"strike": 23400, "type": "PE", "side": "BUY", "lots": 7, "avg_price": 12.5},
        {"strike": 24800, "type": "CE", "side": "BUY", "lots": 7, "avg_price": 5.2},
        {"strike": 25000, "type": "CE", "side": "BUY", "lots": 7, "avg_price": 2.95},
        {"strike": 25200, "type": "CE", "side": "BUY", "lots": 7, "avg_price": 1.8},
        {"role_hint": "ce_sell", "strike": 24200, "type": "CE", "side": "SELL", "lots": 14, "avg_price": 39.05},
    ]


def test_build_fixture_cursor_chat() -> None:
    fx = build_fixture(expiry_date="2026-07-28", legs=_eight_legs(), spot_at_capture=24150.0)
    assert fx["source"] == "cursor_chat"
    assert is_cursor_chat_positions(fx)
    assert len(fx["legs"]) == 8


def test_validate_fixture_rejects_four_legs() -> None:
    legs = _eight_legs()[:4]
    with pytest.raises(UATChatPositionsError, match="exactly 8"):
        build_fixture(expiry_date="2026-07-28", legs=legs)


def test_validate_fixture_rejects_missing_pe_buy() -> None:
    legs = _eight_legs()
    # Flip all PE buys to CE buys → zero PE BUY
    for leg in legs:
        if leg["side"] == "BUY" and leg["type"] == "PE":
            leg["type"] = "CE"
            leg["strike"] = 24600
    with pytest.raises(UATChatPositionsError, match="at least 1 PE BUY"):
        validate_fixture({"legs": legs, "expiry_date": "2026-07-28"})


def test_validate_fixture_rejects_two_pe_sells() -> None:
    legs = _eight_legs()
    legs[-1] = {
        "role_hint": "pe_sell",
        "strike": 23500,
        "type": "PE",
        "side": "SELL",
        "lots": 14,
        "avg_price": 30.0,
    }
    with pytest.raises(UATChatPositionsError, match="1 PE SELL and 1 CE SELL"):
        validate_fixture({"legs": legs, "expiry_date": "2026-07-28"})


def test_register_ingest_prefers_cursor_chat(tmp_path: Path) -> None:
    shot_dir = tmp_path / "uat" / "deployed_positions"
    shot_dir.mkdir(parents=True)
    fx = build_fixture(expiry_date="2026-07-28", legs=_eight_legs())
    pos = shot_dir / "positions.json"
    pos.write_text(json.dumps(fx), encoding="utf-8")
    (shot_dir / "bad.png").write_bytes(b"x")

    with (
        patch("core.uat_ingest.is_uat", return_value=True),
        patch("core.uat_ingest.workspace_root", return_value=tmp_path),
        patch("core.uat_ingest.positions_json_path", return_value=pos),
        patch("core.uat_chat_positions.positions_json_path", return_value=pos),
        patch("core.uat_ingest.uat_screenshot_dir", return_value=shot_dir),
        patch("backtest_engine.uat.sensibull_parser.parse_sensibull_image") as ocr,
    ):
        result = ingest_uat_for_register(tmp_path)
        ocr.assert_not_called()

    assert result.get("method") == "cursor_chat"


def test_duplicate_buy_role_hints_allowed() -> None:
    legs = _eight_legs()
    for leg in legs:
        if leg["side"] == "BUY" and leg["type"] == "PE":
            leg["role_hint"] = "pe_buy"
    fx = build_fixture(expiry_date="2026-07-28", legs=legs)
    assert len(fx["legs"]) == 8
