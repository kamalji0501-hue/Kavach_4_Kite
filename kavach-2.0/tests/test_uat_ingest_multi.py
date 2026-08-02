"""UAT ingest — screenshot OCR only; no stale positions.json fallback."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.uat_ingest import UATIngestError, ingest_uat_screenshot


def test_ingest_raises_when_ocr_fails_despite_existing_positions_json(tmp_path: Path) -> None:
    shot_dir = tmp_path / "uat" / "deployed_positions"
    shot_dir.mkdir(parents=True)
    (shot_dir / "bad.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    pos = shot_dir / "positions.json"
    book = {
        "source": "sensibull",
        "source_image": "good.png",
        "legs": [
            {"role_hint": "pe_sell", "strike": 23200, "type": "PE", "side": "SELL", "lots": 2, "avg_price": 1},
            {"role_hint": "pe_buy", "strike": 23250, "type": "PE", "side": "BUY", "lots": 1, "avg_price": 1},
            {"role_hint": "ce_buy", "strike": 23750, "type": "CE", "side": "BUY", "lots": 1, "avg_price": 1},
            {"role_hint": "ce_sell", "strike": 23800, "type": "CE", "side": "SELL", "lots": 2, "avg_price": 1},
        ],
        "expiry_date": "2026-06-09",
        "spot_at_capture": 23400,
    }
    pos.write_text(json.dumps(book), encoding="utf-8")

    with (
        patch("core.uat_ingest.is_uat", return_value=True),
        patch("core.uat_ingest.uat_screenshot_dir", return_value=shot_dir),
        patch("core.uat_ingest.positions_json_path", return_value=pos),
        patch("bat_telegram.bots.kavach.bot._find_active_deployment", return_value=None),
        patch(
            "backtest_engine.uat.sensibull_parser.parse_sensibull_image",
            side_effect=ValueError("OCR fail"),
        ),
    ):
        with pytest.raises(UATIngestError):
            ingest_uat_screenshot(tmp_path, required=True, newest_only=True)
