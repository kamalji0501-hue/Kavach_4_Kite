"""Tests for independence features (cache heartbeat, health, severity, idempotency)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.ato_idempotency import ato_order_key, get_existing_ato_order, record_ato_order
from core.bot_health import read_bot_health, write_bot_health
from core.incident_severity import resolve_incident_severity
from core.nifty_ltp_feed import NiftyLtpCacheSnapshot, cache_consumer_status, write_nifty_ltp_cache

_IST = ZoneInfo("Asia/Kolkata")


def test_cache_heartbeat_fields(tmp_path: Path) -> None:
    cache = tmp_path / "nifty_ltp_cache.json"
    now = datetime.now(_IST).isoformat()
    snap = NiftyLtpCacheSnapshot(
        ltp=23300.0,
        updated_at=now,
        last_changed_at=now,
        feed_healthy=True,
        poll_interval_seconds=2,
        collector="drishti",
        collector_pid=12345,
    )
    write_nifty_ltp_cache(snap, cache)
    ok, detail = cache_consumer_status(path=cache)
    assert ok is True
    assert "23,300" in detail
    raw = cache.read_text(encoding="utf-8")
    assert "ready_for_consumers" in raw
    assert "cache_age_seconds" in raw


def test_bot_health_roundtrip(tmp_path: Path) -> None:
    write_bot_health(tmp_path, "drishti", extra={"nifty_cache_ready": True})
    data = read_bot_health(tmp_path, "drishti")
    assert data is not None
    assert data["bot"] == "drishti"
    assert data["nifty_cache_ready"] is True


def test_incident_severity_routing() -> None:
    assert resolve_incident_severity("drishti", "nifty_ltp_stale_cache", "error") == "warning"
    assert resolve_incident_severity("kavach", "order_rejection", "error") == "critical"
    assert resolve_incident_severity("kavach", "unknown_scenario", "error") == "warning"


def test_ato_idempotency_keys(state) -> None:
    key = ato_order_key("CE", "BUY", "NIFTY-Jun2026-23350-CE")
    assert get_existing_ato_order(state, key) is None
    record_ato_order(state, key, "SHADOW-00001")
    assert get_existing_ato_order(state, key) == "SHADOW-00001"
