"""Tests for incident knowledge registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.incident_knowledge import (
    IncidentRecord,
    build_dashboard,
    load_registry,
    save_registry,
    search_similar,
    seed_registry_if_empty,
    upsert_incident,
)
from core.incident_seed import build_seed_incidents


def test_seed_builds_stab_and_june25() -> None:
    items = build_seed_incidents()
    ids = {i.incident_id for i in items}
    assert "INC-2026-STAB-01" in ids
    assert "INC-2026-016" in ids
    assert len(items) >= 20


def test_upsert_and_load(tmp_path: Path) -> None:
    reg = tmp_path / "registry.json"
    rec = IncidentRecord(
        incident_id="INC-TEST-001",
        title="Test incident",
        category="testing",
        lifecycle="new",
        symptoms="unit test",
    )
    upsert_incident(rec, reg)
    loaded = load_registry(reg)
    assert len(loaded) == 1
    assert loaded[0].title == "Test incident"


def test_search_similar_finds_websocket(tmp_path: Path) -> None:
    reg = tmp_path / "registry.json"
    save_registry(build_seed_incidents(), reg)
    hits = search_similar(
        "websocket stale failover grace reconnect",
        incidents=load_registry(reg),
    )
    assert hits
    assert any("017" in h[0].incident_id or "STAB" in h[0].incident_id for h in hits)


def test_dashboard_metrics(tmp_path: Path) -> None:
    reg = tmp_path / "registry.json"
    save_registry(build_seed_incidents(), reg)
    dash = build_dashboard(load_registry(reg))
    assert dash["total"] >= 20
    assert dash["closed"] >= 15
    assert "market_data" in dash["by_category"]


def test_seed_registry_if_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = tmp_path / "registry.json"
    monkeypatch.setattr("core.incident_knowledge.DEFAULT_REGISTRY_PATH", reg)
    count = seed_registry_if_empty(reg)
    assert count >= 20
    assert reg.is_file()
    assert seed_registry_if_empty(reg) == 0
