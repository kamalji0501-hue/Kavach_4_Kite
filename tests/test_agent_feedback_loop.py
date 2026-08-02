"""Smoke tests for agent feedback loop helpers."""

from __future__ import annotations

from pathlib import Path

from core.agent_feedback_loop import CycleResult, StepResult, write_latest_report


def test_write_latest_report(tmp_path: Path, monkeypatch) -> None:
    import core.agent_feedback_loop as mod

    monkeypatch.setattr(mod, "_OUT_DIR", tmp_path)
    cycles = [
        CycleResult(
            cycle=1,
            steps=[
                StepResult("pytest_core", True, "ok", 1.0),
                StepResult("session_log_scan", True, "clean", 0.5),
            ],
        )
    ]
    path = write_latest_report(cycles, run_id="test_run", elapsed_s=2.0)
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "PASS" in text
    assert "pytest_core" in text
