"""Tests for bot lifecycle reconcile."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.bot_process_status import BotProcessStatus, BotRunState


def test_reconcile_ghost_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.bot_lifecycle import reconcile_bot

    lock = tmp_path / "data" / "uat" / "kavach.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("15892", encoding="utf-8")

    monkeypatch.setattr(
        "core.bot_process_status.bot_lock_path",
        lambda _robot, root=None: lock,
    )

    fake_stopped = BotProcessStatus(
        robot="kavach",
        runner_marker="run_kavach.py",
        lock_path=lock,
        pids=(),
        lock_pid=None,
        state=BotRunState.STOPPED,
        warnings=(),
    )
    fake_ghost = BotProcessStatus(
        robot="kavach",
        runner_marker="run_kavach.py",
        lock_path=lock,
        pids=(),
        lock_pid=15892,
        state=BotRunState.GHOST_LOCK,
        warnings=("stale",),
    )

    calls = {"n": 0}

    def fake_classify(robot: str, *, root=None):
        calls["n"] += 1
        return fake_ghost if calls["n"] == 1 else fake_stopped

    monkeypatch.setattr("core.bot_lifecycle.classify_bot", fake_classify)
    monkeypatch.setattr("core.bot_lifecycle.heal_stale_lock", lambda *_a, **_k: True)
    monkeypatch.setattr("core.bot_lifecycle.remove_stale_lock", lambda *_a, **_k: True)

    result = reconcile_bot("kavach", root=tmp_path)
    assert result.state is BotRunState.STOPPED
    assert "ghost" in result.action or "stale" in result.action
