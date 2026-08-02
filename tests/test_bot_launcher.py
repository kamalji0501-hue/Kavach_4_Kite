"""Tests for bot launcher preflight (no live WMI)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.bot_launcher import ensure_stopped_for_start
from core.bot_process_status import BotProcessStatus, BotRunState


def _status(robot: str, state: BotRunState, *, pids: tuple[int, ...] = ()) -> BotProcessStatus:
    return BotProcessStatus(
        robot=robot,
        runner_marker=f"run_{robot}.py",
        lock_path=Path(f"data/{robot}.lock"),
        pids=pids,
        lock_pid=pids[0] if pids else None,
        state=state,
        warnings=(),
    )


def test_ensure_stopped_ok_when_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.bot_launcher.classify_bot",
        lambda *_a, **_k: _status("drishti", BotRunState.STOPPED),
    )
    code, status = ensure_stopped_for_start("drishti")
    assert code == 0
    assert status.state is BotRunState.STOPPED


def test_ensure_stopped_blocks_when_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.bot_launcher.classify_bot",
        lambda *_a, **_k: _status("kavach", BotRunState.RUNNING, pids=(1, 2)),
    )
    code, status = ensure_stopped_for_start("kavach")
    assert code == 1
    assert status.state is BotRunState.RUNNING


def test_ensure_stopped_fixes_ghost_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def classify(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _status("jagran", BotRunState.GHOST_LOCK)
        return _status("jagran", BotRunState.STOPPED)

    monkeypatch.setattr("core.bot_launcher.classify_bot", classify)
    monkeypatch.setattr(
        "core.bot_launcher.remove_stale_lock",
        lambda _p, runner_marker=None: True,
    )
    code, status = ensure_stopped_for_start("jagran")
    assert code == 0
    assert status.state is BotRunState.STOPPED
