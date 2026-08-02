"""Tests for shared feed recovery ownership."""

from __future__ import annotations

from pathlib import Path

from core.algo_control import pause_algo
from core.feed_recovery import (
    OWNER_DRISHTI,
    OWNER_OPERATOR,
    can_auto_resume_feed_recovery,
    clear_feed_degraded,
    clear_recovery_at_eod,
    clear_recovery_on_batman_complete,
    evaluate_kavach_resume,
    feed_ready_stable_seconds,
    get_recovery_owner,
    is_feed_degraded,
    kavach_resume_button_spec,
    mark_feed_degraded,
    set_recovery_owner,
    should_auto_resume_ato,
    should_notify_operator_feed_ready,
    should_send_recovery_alert,
    update_feed_ready_stability,
)


def test_recovery_owner_defaults_to_drishti(tmp_path: Path) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    assert get_recovery_owner(state_path) == OWNER_DRISHTI
    assert should_auto_resume_ato(state_path) is True


def test_operator_blocks_auto_resume(tmp_path: Path) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    set_recovery_owner(OWNER_OPERATOR, by="test", state_path=state_path)
    assert should_auto_resume_ato(state_path) is False


def test_kavach_resume_blocked_when_degraded_and_drishti_owns(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "core.feed_recovery.is_nifty_cache_trading_ready",
        lambda: (False, 120.0),
    )
    mark_feed_degraded(state_path=state_path)
    allowed, msg = evaluate_kavach_resume(
        "nifty_ltp_websocket_failed",
        state_path=state_path,
    )
    assert allowed is False
    assert "not ready" in msg.lower()


def test_kavach_resume_blocked_for_feed_even_under_operator(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "core.feed_recovery.is_nifty_cache_trading_ready",
        lambda: (False, 120.0),
    )
    pause_algo(reason="nifty_ltp_websocket_failed", state_path=state_path)
    mark_feed_degraded(state_path=state_path)
    set_recovery_owner(OWNER_OPERATOR, by="test", state_path=state_path)
    allowed, _ = evaluate_kavach_resume(
        "nifty_ltp_websocket_failed",
        state_path=state_path,
    )
    assert allowed is False
    label, action = kavach_resume_button_spec(
        "nifty_ltp_websocket_failed",
        state_path=state_path,
    )
    from core.feed_recovery import LABEL_WAITING_FOR_FEED

    assert label == LABEL_WAITING_FOR_FEED
    assert action == "resume_blocked"


def test_kavach_manual_pause_ignores_feed_rules(tmp_path: Path) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    pause_algo(reason="kavach_manual", state_path=state_path)
    mark_feed_degraded(state_path=state_path)
    allowed, msg = evaluate_kavach_resume("kavach_manual", state_path=state_path)
    assert allowed is True
    assert msg == ""


def test_feed_incident_downgrade_under_operator(tmp_path: Path) -> None:
    from core.feed_recovery import feed_incident_severity

    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    assert feed_incident_severity("critical", state_path=state_path) == "critical"
    set_recovery_owner(OWNER_OPERATOR, state_path=state_path)
    assert feed_incident_severity("critical", state_path=state_path) == "warning"


def test_batman_complete_clears_recovery(tmp_path: Path) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    set_recovery_owner(OWNER_OPERATOR, state_path=state_path)
    mark_feed_degraded(state_path=state_path)
    clear_recovery_on_batman_complete(state_path=state_path)
    assert get_recovery_owner(state_path) == OWNER_DRISHTI
    assert is_feed_degraded(state_path) is False


def test_eod_clears_recovery_lock(tmp_path: Path) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    set_recovery_owner(OWNER_OPERATOR, state_path=state_path)
    mark_feed_degraded(state_path=state_path)
    assert clear_recovery_at_eod(state_path=state_path) is True
    assert get_recovery_owner(state_path) == OWNER_DRISHTI


def test_operator_ready_notify_once(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    pause_algo(reason="test", state_path=state_path)
    set_recovery_owner(OWNER_OPERATOR, state_path=state_path)
    mark_feed_degraded(state_path=state_path)

    monkeypatch.setattr(
        "core.feed_recovery.is_nifty_cache_trading_ready",
        lambda: (True, 2.0),
    )
    assert should_notify_operator_feed_ready(state_path=state_path) is True
    assert should_notify_operator_feed_ready(state_path=state_path) is False


def test_alert_throttle_30s(tmp_path: Path) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    mark_feed_degraded(state_path=state_path)
    assert should_send_recovery_alert(state_path=state_path) is True
    assert should_send_recovery_alert(state_path=state_path) is False
    clear_feed_degraded(state_path=state_path)


def test_sustained_feed_required_before_auto_resume(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    pause_algo(reason="nifty_ltp_feed_stale", state_path=state_path)

    monkeypatch.setattr(
        "core.feed_recovery.is_nifty_cache_trading_ready",
        lambda: (True, 2.0),
    )
    update_feed_ready_stability(ready=True, state_path=state_path)
    assert can_auto_resume_feed_recovery(state_path=state_path) is False
    assert (feed_ready_stable_seconds(state_path=state_path) or 0) < 45

    blob_path = state_path
    from core.state import StateManager

    sm = StateManager(blob_path)
    blob = sm.get("nifty_feed_recovery") or {}
    blob["feed_ready_since"] = "2020-01-01T10:00:00+05:30"
    sm.set("nifty_feed_recovery", blob)
    assert can_auto_resume_feed_recovery(state_path=state_path) is True


def test_mark_degraded_clears_feed_ready_stability(tmp_path: Path) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text("{}", encoding="utf-8")
    update_feed_ready_stability(ready=True, state_path=state_path)
    assert feed_ready_stable_seconds(state_path=state_path) is not None
    mark_feed_degraded(state_path=state_path)
    assert feed_ready_stable_seconds(state_path=state_path) is None
