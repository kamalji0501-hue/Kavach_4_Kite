"""UAT register cleanup — fresh slate before OCR."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.uat_register_cleanup import prepare_uat_register_fresh


def test_prepare_uat_register_fresh_removes_positions_json(tmp_path: Path) -> None:
    shot_dir = tmp_path / "uat" / "deployed_positions"
    shot_dir.mkdir(parents=True)
    pos = shot_dir / "positions.json"
    pos.write_text(json.dumps({"legs": []}), encoding="utf-8")

    broker = MagicMock()
    broker._orders = {"x": 1}

    with (
        patch("core.uat_register_cleanup.is_uat", return_value=True),
        patch("core.uat_register_cleanup.positions_json_path", return_value=pos),
        patch("core.uat_register_cleanup.workspace_root", return_value=tmp_path),
        patch("bat_telegram.bots.kavach.bot._archive_active_deployments", return_value=[]),
    ):
        summary = prepare_uat_register_fresh(tmp_path, broker=broker)

    assert summary.get("removed_positions_json") is True
    assert not pos.is_file()
    assert broker._orders == {}
