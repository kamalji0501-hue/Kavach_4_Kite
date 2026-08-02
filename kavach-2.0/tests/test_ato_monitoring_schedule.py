"""Tests for KAVACH ATO monitoring schedule helpers."""

from __future__ import annotations

import zoneinfo
from datetime import datetime
from unittest.mock import patch

from core.ato_monitoring_schedule import (
    ato_session_open_for_breach,
    format_monitoring_schedule_line,
    is_past_monitoring_start,
    is_waiting_for_monitoring_start,
    monitoring_start_hhmm,
)

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def test_default_start_time() -> None:
    assert monitoring_start_hhmm() == "09:25"


def test_waiting_during_pre_start_session() -> None:
    now = datetime(2026, 6, 9, 9, 20, tzinfo=_IST)  # Monday, in session, before 09:25
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        assert is_waiting_for_monitoring_start(now, deployed=True) is True
        assert is_past_monitoring_start(now) is False
        line = format_monitoring_schedule_line(deployed=True, now=now)
    assert "Waiting" in line
    assert "09:25" in line


def test_active_after_start() -> None:
    now = datetime(2026, 6, 9, 10, 0, tzinfo=_IST)
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        assert is_waiting_for_monitoring_start(now, deployed=True) is False
        assert is_past_monitoring_start(now) is True
        line = format_monitoring_schedule_line(deployed=True, now=now)
    assert "active" in line.lower()


def test_not_deployed_no_wait() -> None:
    now = datetime(2026, 6, 9, 9, 20, tzinfo=_IST)
    assert is_waiting_for_monitoring_start(now, deployed=False) is False
    line = format_monitoring_schedule_line(deployed=False, now=now)
    assert "Not armed" in line


def test_uat_replay_unlocks_off_hours() -> None:
    now = datetime(2026, 7, 16, 22, 0, tzinfo=_IST)  # evening — outside NSE session
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=True):
        assert is_past_monitoring_start(now) is True
        assert is_waiting_for_monitoring_start(now, deployed=True) is False
        assert ato_session_open_for_breach(now) is True
        line = format_monitoring_schedule_line(deployed=True, now=now)
    assert "UAT replay" in line


def test_off_hours_without_replay_stays_idle() -> None:
    now = datetime(2026, 7, 16, 22, 0, tzinfo=_IST)
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        assert is_past_monitoring_start(now) is False
        assert ato_session_open_for_breach(now) is False
