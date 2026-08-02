"""Tests for bulk launcher logging and stop-all retry logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.launcher_session_log import launcher_errors_dir, launcher_logs_dir
from scripts.phase1_stop_all import _all_stopped, run_stop_all


def test_launcher_log_dirs(tmp_path: Path) -> None:
    logs = launcher_logs_dir(tmp_path, "stop_all")
    errs = launcher_errors_dir(tmp_path, "start_all")
    assert "launchers" in str(logs)
    assert logs.name == "logs"
    assert "stop_all" in str(logs)
    assert "start_all" in str(errs)


def test_session_logger_writes_all_log(tmp_path: Path) -> None:
    from core.launcher_session_log import LauncherSessionLogger

    log = LauncherSessionLogger(tmp_path, "stop_all")
    log.info("test line")
    path = launcher_logs_dir(tmp_path, "stop_all") / "all.log"
    assert path.exists()
    assert "test line" in path.read_text(encoding="utf-8")


def test_all_stopped_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.phase1_stop_all.all_stopped", lambda **_k: (True, []))
    ok, lines = _all_stopped()
    assert ok is True
    assert lines == []


def test_stop_all_succeeds_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.phase1_stop_all._stop_once",
        lambda **_k: True,
    )
    monkeypatch.setattr(
        "scripts.phase1_stop_all._all_stopped",
        lambda: (True, []),
    )
    monkeypatch.setattr("scripts.phase1_stop_all.show_error_popup", lambda *_a, **_k: None)
    rc = run_stop_all(popup_on_failure=False, max_attempts=3)
    assert rc == 0


def test_stop_all_retries_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def not_stopped() -> tuple[bool, list[str]]:
        calls["n"] += 1
        return False, ["KAVACH: RUNNING"]

    monkeypatch.setattr("scripts.phase1_stop_all._stop_once", lambda **_k: True)
    monkeypatch.setattr("scripts.phase1_stop_all._all_stopped", not_stopped)
    monkeypatch.setattr("scripts.phase1_stop_all.show_error_popup", lambda *_a, **_k: None)
    rc = run_stop_all(popup_on_failure=False, max_attempts=2)
    assert rc == 2
    assert calls["n"] == 2
