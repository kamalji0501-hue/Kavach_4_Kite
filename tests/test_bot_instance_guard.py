"""Tests for exclusive bot instance bootstrap."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from core.bot_process_status import BotProcessStatus, BotRunState


def test_scan_phase1_bots_returns_three(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.bot_instance_guard import scan_phase1_bots
    from core.bot_process_status import PHASE1_BOTS

    def fake(robot: str, *, root=None):
        return BotProcessStatus(
            robot=robot,
            runner_marker=f"run_{robot}.py",
            lock_path=Path(f"data/{robot}.lock"),
            pids=(),
            lock_pid=None,
            state=BotRunState.STOPPED,
            warnings=(),
        )

    monkeypatch.setattr("core.bot_instance_guard.classify_bot", fake)
    tray = scan_phase1_bots(root=Path("."))
    assert set(tray) == set(PHASE1_BOTS)


def test_bootstrap_calls_reclaim_and_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from core.bot_instance_guard import bootstrap_exclusive_bot

    calls: list[str] = []

    monkeypatch.setattr(
        "core.bot_instance_guard.log_process_tray",
        lambda *_a, **_k: calls.append("scan"),
    )
    monkeypatch.setattr(
        "core.bot_instance_guard.reclaim_same_bot_instances",
        lambda *_a, **_k: calls.append("reclaim") or 0,
    )
    monkeypatch.setattr(
        "core.bot_instance_guard.ensure_single_instance",
        lambda *_a, **_k: calls.append("lock"),
    )
    lock = tmp_path / "drishti.lock"
    bootstrap_exclusive_bot("drishti", lock, logging.getLogger("test"), root=tmp_path)
    assert calls == ["scan", "reclaim", "lock"]
