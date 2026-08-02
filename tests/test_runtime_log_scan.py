"""Tests for runtime log session scan."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.runtime_log_scan import (
    current_session_lines,
    is_benign_transient_log_error,
    scan_robot_session_errors,
)

_IST = ZoneInfo("Asia/Kolkata")


def test_current_session_lines_finds_latest_startup() -> None:
    lines = [
        "100000 | DRISHTI | Batman mode: dev",
        "100100 | DRISHTI | ERROR | old session",
        "110000 | DRISHTI | Batman mode: uat",
        "110100 | DRISHTI | INFO | fresh start",
    ]
    window = current_session_lines(lines, "drishti", tail_lines=100)
    assert "fresh start" in window[-1]
    assert not any("old session" in ln for ln in window)


def test_benign_ltp_failure_when_cache_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.feed_recovery.is_nifty_cache_trading_ready",
        lambda: (True, 2.0),
    )
    line = "ERROR | ATO | 5 consecutive LTP cache failures"
    assert is_benign_transient_log_error(line) is True


def test_scan_session_ignores_benign_when_feed_healthy(tmp_path: Path, monkeypatch) -> None:
    when = datetime(2026, 6, 25, 12, 0, tzinfo=_IST)
    log_dir = tmp_path / "2026-06" / "2026-06-25" / "kavach" / "logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "all.log"
    log_path.write_text(
        "110000 | INFO | KAVACH | Batman mode: uat\n"
        "110100 | ERROR | ATO_PROTECTION | 5 consecutive LTP cache failures\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "core.feed_recovery.is_nifty_cache_trading_ready",
        lambda: (True, 2.0),
    )
    hits = scan_robot_session_errors(log_path, "kavach")
    assert hits == []
