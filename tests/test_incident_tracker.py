"""Tests for domain incident tracker."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.incident_tracker import (
    _REPEAT_JAGRAN_THRESHOLD,
    INCIDENT_DOMAINS,
    build_weekly_rollup,
    close_incident,
    domain_csv_path,
    export_dashboard_xlsx,
    list_open_incidents,
    record_incident,
    resolve_domain_incident,
    summarize_domain_day,
)

_IST = ZoneInfo("Asia/Kolkata")


def _patch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "incidents"

    def _root_dir() -> Path:
        return base

    monkeypatch.setattr("core.incident_tracker.incidents_root_dir", _root_dir)
    monkeypatch.setattr("core.incident_tracker._ACTIVE", {})
    monkeypatch.setattr("core.incident_tracker._registry_loaded", True)
    monkeypatch.setattr(
        "core.incident_tracker._mirror_global_ledger",
        lambda **_k: None,
    )


def test_domains_include_main() -> None:
    assert "main" in INCIDENT_DOMAINS
    assert len(INCIDENT_DOMAINS) == 6


def test_record_operator_status_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(tmp_path, monkeypatch)
    reg_path = tmp_path / "incidents" / "open_registry.json"
    record_incident(
        domain="stop_all",
        scenario="stop_all_failure",
        message="bot still running",
        cause_hint="run stop bat",
    )
    path = domain_csv_path("stop_all")
    text = path.read_text(encoding="utf-8")
    assert "operator_status" in text
    assert "open" in text
    assert reg_path.exists()
    assert list_open_incidents("stop_all")


def test_resolve_closes_operator_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(tmp_path, monkeypatch)
    record_incident(domain="kavach", scenario="test_scenario", message="err")
    resolve_domain_incident(
        domain="kavach",
        scenario="test_scenario",
        resolution_message="fixed",
    )
    assert not list_open_incidents("kavach")
    text = domain_csv_path("kavach").read_text(encoding="utf-8")
    assert "closed" in text


def test_repeat_jagran_at_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(tmp_path, monkeypatch)
    notified: list[int] = []

    def fake_notify(**_kwargs: object) -> None:
        notified.append(1)

    monkeypatch.setattr("core.incident_tracker._notify_jagran_async", fake_notify)
    monkeypatch.setattr("core.incident_tracker._DEDUP_SECONDS", 0)

    msg = "same error message for repeat test"
    for _ in range(_REPEAT_JAGRAN_THRESHOLD):
        record_incident(
            domain="drishti",
            scenario="repeat_test",
            message=msg,
            title="Repeat Test",
        )
    assert len(notified) >= 1


def test_weekly_rollup_and_xlsx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(tmp_path, monkeypatch)
    end = datetime.now(_IST)
    record_incident(
        domain="main",
        scenario="heartbeat_fail",
        message="loop error",
    )
    rollup = build_weekly_rollup(days=7, end=end)
    assert rollup["total_incidents"] >= 1
    assert "main" in rollup["by_domain_totals"]
    out = tmp_path / "dash.xlsx"
    export_dashboard_xlsx(out, days=7, end=end)
    assert out.exists()
    assert out.stat().st_size > 0


def test_summarize_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(tmp_path, monkeypatch)
    summary = summarize_domain_day("drishti")
    assert summary["total"] == 0


def test_close_incident_by_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(tmp_path, monkeypatch)
    record_incident(domain="jagran", scenario="test_close", message="err")
    assert close_incident(incident_id="jagran::test_close", note="ops done")
    assert not list_open_incidents("jagran")


def test_repeat_jagran_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(tmp_path, monkeypatch)
    notified: list[int] = []

    def fake_notify(**_kwargs: object) -> None:
        notified.append(1)

    monkeypatch.setattr("core.incident_tracker._notify_jagran_async", fake_notify)
    monkeypatch.setattr("core.incident_tracker._DEDUP_SECONDS", 0)

    msg = "repeat once test"
    for _ in range(6):
        record_incident(domain="kavach", scenario="once_jagran", message=msg, title="Once")
    assert len(notified) == 1
