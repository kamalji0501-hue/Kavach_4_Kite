"""Tests for core.bot_health."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.bot_health import health_age_seconds, health_confirms_running, write_bot_health

_IST = ZoneInfo("Asia/Kolkata")


def test_health_age_seconds_fresh() -> None:
    now = datetime.now(_IST)
    health = {"updated_at": now.isoformat(), "status": "running", "pid": 1234}
    age = health_age_seconds(health, now=now)
    assert age is not None
    assert age < 1.0


def test_health_confirms_running_matching_pid(tmp_path) -> None:
    import os

    write_bot_health(tmp_path, "drishti")
    ok, age = health_confirms_running(tmp_path, "drishti", (os.getpid(),))
    assert ok is True
    assert age is not None
