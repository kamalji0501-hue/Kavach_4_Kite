"""Tests for bot process / lock classification (no live WMI)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.batman_mode import bot_lock_path
from core.bot_process_status import BotRunState, classify_bot, remove_stale_lock


@pytest.fixture
def runtime_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    rr = tmp_path / "Batman-Runtime"
    monkeypatch.setenv("BATMAN_RUNTIME_ROOT", str(rr))
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "batman_mode.json").write_text('{"mode": "uat"}', encoding="utf-8")
    return tmp_path


def test_stopped_no_lock_no_pids(runtime_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.bot_process_status._find_pids",
        lambda _marker: [],
    )
    monkeypatch.setattr(
        "core.bot_process_status._lock_pid_alive",
        lambda _pid: False,
    )
    status = classify_bot("drishti", root=runtime_ws)
    assert status.state is BotRunState.STOPPED
    assert status.pids == ()


def test_running_with_matching_lock(runtime_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.bot_process_status._find_pids",
        lambda _marker: [100, 101],
    )
    monkeypatch.setattr(
        "core.bot_process_status._lock_pid_alive",
        lambda pid: pid == 101,
    )
    lock = bot_lock_path("drishti", runtime_ws)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("101", encoding="utf-8")
    status = classify_bot("drishti", root=runtime_ws)
    assert status.state is BotRunState.RUNNING
    assert status.lock_pid == 101


def test_orphan_running_without_lock(runtime_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.bot_process_status._find_pids",
        lambda _marker: [200],
    )
    status = classify_bot("kavach", root=runtime_ws)
    assert status.state is BotRunState.ORPHAN
    assert "lock file is missing" in status.warnings[0]


def test_ghost_lock_dead_pid(runtime_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.bot_process_status._find_pids",
        lambda _marker: [],
    )
    monkeypatch.setattr(
        "core.bot_process_status._lock_pid_alive",
        lambda _pid: False,
    )
    lock = bot_lock_path("jagran", runtime_ws)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="utf-8")
    status = classify_bot("jagran", root=runtime_ws)
    assert status.state is BotRunState.GHOST_LOCK
    assert remove_stale_lock(lock) is True
    assert not lock.exists()


def test_ghost_lock_recycled_pid(runtime_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.bot_process_status._find_pids",
        lambda _marker: [],
    )
    monkeypatch.setattr(
        "core.bot_process_status._lock_pid_alive",
        lambda _pid: True,
    )
    monkeypatch.setattr(
        "core.bot_process_status._lock_pid_owns_runner",
        lambda _pid, _marker: False,
    )
    lock = bot_lock_path("kavach", runtime_ws)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("15892", encoding="utf-8")
    status = classify_bot("kavach", root=runtime_ws)
    assert status.state is BotRunState.GHOST_LOCK
    assert remove_stale_lock(lock, runner_marker="run_kavach2.py") is True
    assert not lock.exists()


def test_diagnose_reports_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.bot_process_status import BotProcessStatus

    fake = BotProcessStatus(
        robot="drishti",
        runner_marker="run_drishti.py",
        lock_path=Path("data/drishti.lock"),
        pids=(42,),
        lock_pid=42,
        state=BotRunState.RUNNING,
        warnings=(),
    )
    monkeypatch.setattr("scripts.diagnose_robot.classify_bot", lambda *_a, **_k: fake)
    from scripts.diagnose_robot import diagnose

    assert diagnose("drishti") == 0


def test_running_recovered_from_fresh_health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from core.bot_health import write_bot_health

    calls = {"n": 0}

    def find_pids(_marker: str) -> list[int]:
        calls["n"] += 1
        return [300] if calls["n"] >= 2 else []

    monkeypatch.setattr("core.bot_process_status._find_pids", find_pids)
    monkeypatch.setattr(
        "core.bot_process_status._lock_pid_alive",
        lambda _pid: False,
    )
    write_bot_health(tmp_path, "drishti")
    monkeypatch.setattr(
        "core.bot_health.os.getpid",
        lambda: os.getpid(),
        raising=False,
    )
    status = classify_bot("drishti", root=tmp_path)
    assert status.state is BotRunState.RUNNING
    assert status.pids == (300,)
