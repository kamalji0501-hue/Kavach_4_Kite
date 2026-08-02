"""Tests for NIFTY transport-specific audit logs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.nifty_ltp_audit import (
    NiftyLtpBatchLogWriter,
    append_rest_ltp_log,
    append_websocket_ltp_log,
    format_tick_log_line,
)

_IST = ZoneInfo("Asia/Kolkata")


def test_format_tick_log_line_minimal() -> None:
    now = datetime(2026, 6, 7, 9, 15, 0, 125000, tzinfo=_IST)
    assert format_tick_log_line(now, 25231.5) == "09:15:00.125 | 25231.50\n"


def test_format_tick_log_line_with_event() -> None:
    now = datetime(2026, 6, 7, 9, 20, 1, tzinfo=_IST)
    line = format_tick_log_line(now, 0.0, event="reconnect")
    assert line == "09:20:01.000 | 0.00 | reconnect\n"


def test_append_rest_ltp_log(tmp_path: Path) -> None:
    now = datetime(2026, 6, 7, 10, 0, 2, tzinfo=_IST)
    path = append_rest_ltp_log(tmp_path, now, 25240.1)
    assert path.name == "rest_ltp_20260607.log"
    assert path.read_text(encoding="utf-8").strip() == "10:00:02.000 | 25240.10"


def test_append_websocket_ltp_log(tmp_path: Path) -> None:
    now = datetime(2026, 6, 7, 10, 0, 3, 500000, tzinfo=_IST)
    path = append_websocket_ltp_log(tmp_path, now, 25240.2, event="tick")
    assert path.name == "ws_ltp_20260607.log"
    assert "25240.20" in path.read_text(encoding="utf-8")


def test_batch_log_writer_flush(tmp_path: Path) -> None:
    writer = NiftyLtpBatchLogWriter(tmp_path, filename_prefix="ws_ltp")
    now = datetime(2026, 6, 7, 11, 0, 0, tzinfo=_IST)
    writer.append_tick(now, 25200.0)
    writer.append_tick(now, 25200.5)
    writer.flush()
    log_path = tmp_path / "ws_ltp_20260607.log"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
