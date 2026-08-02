"""ATO JSONL feed + cycle state for SARANSH (P1)."""

from __future__ import annotations

import json
from pathlib import Path

from core.ato_cycle_feed import (
    append_feed_event,
    read_cycle_state,
    record_ato_buy,
    record_ato_cycle_complete,
)
from core.saransh_paths import ato_cycle_feed_path, ato_cycle_state_path


def _uat_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("BATMAN_MODE", "uat")
    monkeypatch.setenv("BATMAN_DATA_REPORTS_ROOT", str(tmp_path))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "batman_mode.json").write_text(
        '{"mode": "uat", "modes": {"uat": {"data_root": "data/uat"}}}',
        encoding="utf-8",
    )
    return tmp_path


def test_cycle_complete_updates_state(tmp_path: Path, monkeypatch) -> None:
    root = _uat_root(tmp_path, monkeypatch)
    record_ato_buy(
        side="CE",
        sell_strike=24500,
        buy_nifty_ltp=100.0,
        lots=1.0,
        timestamp_ist="2026-06-05 10:00:00 IST",
        deployment_file="batman_20260605.json",
        root=root,
    )
    state = read_cycle_state(root=root)
    assert state["ce"]["holding"] is True
    assert state["ce"]["sell_strike"] == 24500

    impact = record_ato_cycle_complete(
        side="CE",
        sell_strike=24500,
        buy_nifty_ltp=100.0,
        sell_nifty_ltp=98.0,
        lots=1.0,
        timestamp_ist="2026-06-05 10:05:00 IST",
        deployment_file="batman_20260605.json",
        root=root,
    )
    assert impact == -2.0
    state = read_cycle_state(root=root)
    assert state["ce"]["holding"] is False
    assert state["cycles_completed_today"] == 1
    assert state["net_point_impact"] == -2.0

    feed_path = ato_cycle_feed_path(root)
    lines = feed_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    last = json.loads(lines[-1])
    assert last["event"] == "cycle_complete"
    assert last["point_impact"] == -2.0
    assert ato_cycle_state_path(root).is_file()


def test_append_feed_event(tmp_path: Path, monkeypatch) -> None:
    root = _uat_root(tmp_path, monkeypatch)
    append_feed_event({"event": "ping"}, root=root)
    assert ato_cycle_feed_path(root).read_text(encoding="utf-8").strip() == '{"event": "ping"}'
