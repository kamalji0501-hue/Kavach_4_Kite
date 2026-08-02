"""UAT skip for daily 09:25 ATO prompt (OQ-P1-08 / OQ-P1-16)."""

from __future__ import annotations

from pathlib import Path

from core.daily_ato_prompt import daily_ato_prompt_status_line, should_send_daily_ato_prompt


def _write_mode(tmp_path: Path, mode: str) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "batman_mode.json").write_text(
        f'{{"mode": "{mode}", "modes": {{"uat": {{"data_root": "data/uat"}}}}}}',
        encoding="utf-8",
    )


def test_uat_skips_daily_prompt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BATMAN_MODE", "uat")
    _write_mode(tmp_path, "uat")
    assert should_send_daily_ato_prompt(tmp_path) is False
    assert "skipped in UAT" in daily_ato_prompt_status_line(tmp_path)


def test_dev_enables_daily_prompt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BATMAN_MODE", raising=False)
    _write_mode(tmp_path, "dev")
    assert should_send_daily_ato_prompt(tmp_path) is True
