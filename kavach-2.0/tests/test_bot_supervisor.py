"""Tests for bot supervisor (mocked spawn)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_spawn_bot_uses_venv_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.bot_supervisor import spawn_bot

    import sys

    if sys.platform == "win32":
        venv_py = tmp_path / ".venv" / "Scripts"
        venv_py.mkdir(parents=True)
        python = venv_py / "python.exe"
    else:
        venv_py = tmp_path / ".venv" / "bin"
        venv_py.mkdir(parents=True)
        python = venv_py / "python"
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    (tmp_path / "run_drishti.py").write_text("# stub", encoding="utf-8")

    captured: dict = {}

    class FakeProc:
        pid = 4242

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr("core.bot_supervisor.subprocess.Popen", fake_popen)

    spawned = spawn_bot("drishti", root=tmp_path, new_console=False)
    assert spawned.pid == 4242
    assert "run_drishti.py" in captured["args"]


def test_start_all_aborts_when_ltp_gate_fails_in_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core import bot_supervisor

    monkeypatch.setattr(bot_supervisor, "reconcile_all", lambda **kw: [])
    monkeypatch.setattr(bot_supervisor, "stop_all_bots", lambda **kw: 0)
    monkeypatch.setattr(bot_supervisor, "spawn_bot", lambda *a, **kw: MagicMock(pid=1))
    monkeypatch.setattr(bot_supervisor, "wait_bot_running", lambda *a, **kw: True)
    monkeypatch.setattr(
        bot_supervisor,
        "wait_drishti_ltp_ready",
        lambda **kw: (False, "cache stale age=120s"),
    )

    rc = bot_supervisor.start_all_bots(root=tmp_path, new_console=False)
    assert rc == 1


def test_start_all_uses_full_wait_budget_for_ltp_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core import bot_supervisor

    captured: dict[str, float] = {}

    monkeypatch.setattr(bot_supervisor, "reconcile_all", lambda **kw: [])
    monkeypatch.setattr(bot_supervisor, "stop_all_bots", lambda **kw: 0)
    monkeypatch.setattr(bot_supervisor, "spawn_bot", lambda *a, **kw: MagicMock(pid=1))
    monkeypatch.setattr(bot_supervisor, "wait_bot_running", lambda *a, **kw: True)

    def fake_wait_drishti_ltp_ready(**kw):
        captured["timeout_seconds"] = float(kw["timeout_seconds"])
        return (False, "cache stale age=120s")

    monkeypatch.setattr(bot_supervisor, "wait_drishti_ltp_ready", fake_wait_drishti_ltp_ready)

    rc = bot_supervisor.start_all_bots(root=tmp_path, new_console=False, wait_seconds=180.0)
    assert rc == 1
    assert captured["timeout_seconds"] == 180.0

