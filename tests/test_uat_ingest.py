"""UAT ingest helpers — agent verification suite."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.batman_mode import workspace_root


def test_ingest_skipped_when_not_uat() -> None:
    from core.uat_ingest import ingest_uat_screenshot

    root = workspace_root()
    with patch("core.uat_ingest.is_uat", return_value=False):
        result = ingest_uat_screenshot(root)
    assert result.get("skipped") is True


def test_newest_only_tries_single_image(tmp_path: Path) -> None:
    from core.uat_ingest import ingest_uat_screenshot

    shot_dir = tmp_path / "uat" / "deployed_positions"
    shot_dir.mkdir(parents=True)
    older = shot_dir / "old.png"
    newer = shot_dir / "new.png"
    older.write_bytes(b"1")
    newer.write_bytes(b"2")
    import os
    import time

    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time(), time.time()))

    fixture = {
        "legs": [{"role_hint": "pe_sell", "strike": 1, "type": "PE", "side": "SELL", "lots": 1, "avg_price": 1}],
        "expiry_date": "2026-06-09",
        "spot_at_capture": 23400,
    }
    calls: list[str] = []

    def fake_parse(path: Path) -> dict:
        calls.append(path.name)
        return fixture

    with (
        patch("core.uat_ingest.is_uat", return_value=True),
        patch("core.uat_ingest.uat_screenshot_dir", return_value=shot_dir),
        patch("core.uat_ingest.positions_json_path", return_value=shot_dir / "positions.json"),
        patch("bat_telegram.bots.kavach2.bot._find_active_deployment", return_value=None),
        patch("backtest_engine.uat.sensibull_parser.parse_sensibull_image", side_effect=fake_parse),
    ):
        result = ingest_uat_screenshot(tmp_path, required=True, newest_only=True)

    assert result.get("ok") is True
    assert calls == ["new.png"]
