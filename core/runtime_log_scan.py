"""Shared runtime log scan helpers (current session window + transient error filter)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")

ERROR_LINE_PATTERN = re.compile(
    r"Traceback|ERROR\s+\||CRITICAL\s+\||wizard_cancelled.*fail|UATIngestError",
    re.IGNORECASE,
)


def current_session_lines(lines: list[str], robot: str, *, tail_lines: int) -> list[str]:
    """Return log lines for the latest bot session (after last startup marker)."""
    tag = f"| {robot.upper()} |"
    start = 0
    for idx, line in enumerate(lines):
        if tag in line and "Batman mode:" in line:
            start = idx
    window = lines[start:] if start else lines[-tail_lines:]
    if len(window) > tail_lines:
        window = window[-tail_lines:]
    return window


def is_benign_transient_log_error(line: str) -> bool:
    """Ignore errors that are expected during feed recovery when feed is healthy now."""
    if "LTP cache failures" in line or "nifty_ltp_feed_stale" in line.lower():
        try:
            from core.feed_recovery import is_nifty_cache_trading_ready

            ready, _ = is_nifty_cache_trading_ready()
            return ready
        except Exception:
            return False
    if "No NIFTY PE strike" in line and "2026-06-23" in line:
        return True
    if "PE managed qty mismatch" in line:
        return True
    return False


def scan_robot_session_errors(
    log_path: Path,
    robot: str,
    *,
    tail_lines: int = 400,
) -> list[str]:
    if not log_path.is_file():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ["read fail"]
    window = current_session_lines(lines, robot, tail_lines=tail_lines)
    hits: list[str] = []
    for ln in window:
        if not ERROR_LINE_PATTERN.search(ln):
            continue
        if is_benign_transient_log_error(ln):
            continue
        hits.append(ln)
    return hits


def day_log_paths(
    root: Path,
    log_runtime: Path,
    when: datetime | None = None,
) -> dict[str, Path]:
    now = when or datetime.now(tz=_IST)
    base = log_runtime / now.strftime("%Y-%m") / now.strftime("%Y-%m-%d")
    return {robot: base / robot / "logs" / "all.log" for robot in ("drishti", "kavach", "jagran", "saransh")}
