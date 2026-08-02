"""Tests for core.algo_control."""

from __future__ import annotations

from pathlib import Path

from core.algo_control import is_algo_paused, pause_algo, resume_algo
from core.state import StateManager


def test_pause_and_resume_algo(tmp_path: Path) -> None:
    state_path = tmp_path / "batman_state.json"
    StateManager(path=state_path)

    assert pause_algo(reason="nifty_ltp_stale_price", state_path=state_path) is True
    assert is_algo_paused(state_path=state_path) is True
    assert pause_algo(reason="again", state_path=state_path) is False

    sm = StateManager(path=state_path)
    assert sm.get("algo.pause_reason") == "nifty_ltp_stale_price"
    assert sm.get("algo.paused_by") == "drishti"

    assert resume_algo(state_path=state_path) is True
    assert is_algo_paused(state_path=state_path) is False
    sm = StateManager(path=state_path)
    assert sm.get("algo.pause_reason") is None


def test_refresh_algo_flags_from_disk(tmp_path: Path) -> None:
    """KAVACH in-memory state picks up DRISHTI pause written by another process."""
    state_path = tmp_path / "batman_state.json"
    kavach_state = StateManager(path=state_path)
    assert kavach_state.get("algo.paused", False) is False

    pause_algo(reason="nifty_ltp_stale_price", state_path=state_path)

    kavach_state.refresh_algo_flags_from_disk()
    assert kavach_state.get("algo.paused") is True
    assert kavach_state.get("algo.pause_reason") == "nifty_ltp_stale_price"


def test_default_state_path_uses_uat_mode(tmp_path, monkeypatch) -> None:
    from core.algo_control import default_state_path, is_algo_paused, pause_algo

    uat_state = tmp_path / "data" / "uat" / "batman_state.json"
    uat_state.parent.mkdir(parents=True, exist_ok=True)
    uat_state.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("core.algo_control.state_path", lambda root=None: uat_state)

    assert default_state_path() == uat_state
    pause_algo(reason="nifty_ltp_websocket_failed")
    assert is_algo_paused() is True
    assert StateManager(path=uat_state).get("algo.pause_reason") == "nifty_ltp_websocket_failed"
