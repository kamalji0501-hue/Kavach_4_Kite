"""Tests for KAVACH ATO monitoring schedule helpers."""

from __future__ import annotations

import zoneinfo
from datetime import datetime
from unittest.mock import MagicMock, patch

from core.ato_monitoring_schedule import (
    ato_session_open_for_breach,
    format_monitoring_schedule_line,
    is_past_monitoring_start,
    is_waiting_for_monitoring_start,
    monitoring_end_hhmm,
    monitoring_start_hhmm,
)

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def test_default_start_time() -> None:
    assert monitoring_start_hhmm() == "09:20"


def test_default_end_time() -> None:
    assert monitoring_end_hhmm() == "15:25"


def test_waiting_during_pre_start_session() -> None:
    now = datetime(2026, 6, 9, 9, 19, tzinfo=_IST)  # Monday, in session, before 09:20
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        with patch("core.ato_monitoring_schedule._overnight_early_unlock", return_value=False):
            assert is_waiting_for_monitoring_start(now, deployed=True) is True
            assert is_past_monitoring_start(now) is False
            line = format_monitoring_schedule_line(deployed=True, now=now)
    assert "Waiting" in line
    assert "09:20" in line


def test_active_after_start() -> None:
    now = datetime(2026, 6, 9, 10, 0, tzinfo=_IST)
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        assert is_waiting_for_monitoring_start(now, deployed=True) is False
        assert is_past_monitoring_start(now) is True
        line = format_monitoring_schedule_line(deployed=True, now=now)
    assert "active" in line.lower()
    assert "15:25" in line


def test_session_closed_after_1525() -> None:
    now = datetime(2026, 6, 9, 15, 25, 1, tzinfo=_IST)
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        assert ato_session_open_for_breach(now) is False
        assert is_past_monitoring_start(now) is False
    now_exact = datetime(2026, 6, 9, 15, 25, 0, tzinfo=_IST)
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        assert ato_session_open_for_breach(now_exact) is True


def test_overnight_handoff_unlocks_before_0925() -> None:
    now = datetime(2026, 6, 9, 9, 21, tzinfo=_IST)
    state = MagicMock()
    state.get.side_effect = lambda key, default=None: (
        "2026-06-09" if key == "overnight.morning_done_date" else default
    )
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        assert is_waiting_for_monitoring_start(now, deployed=True, state=state) is False
        assert is_past_monitoring_start(now, state=state) is True
        line = format_monitoring_schedule_line(deployed=True, now=now, state=state)
    assert "active" in line.lower()


def test_not_deployed_no_wait() -> None:
    now = datetime(2026, 6, 9, 9, 19, tzinfo=_IST)
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


def test_active_at_0920_without_overnight() -> None:
    now = datetime(2026, 6, 9, 9, 20, tzinfo=_IST)
    with patch("core.ato_monitoring_schedule.is_uat_replay_feed_active", return_value=False):
        with patch("core.ato_monitoring_schedule._overnight_early_unlock", return_value=False):
            assert is_waiting_for_monitoring_start(now, deployed=True) is False
            assert is_past_monitoring_start(now) is True
            assert ato_session_open_for_breach(now) is True
