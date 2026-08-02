"""Tests for JAGRAN incident gating and ledger helpers."""

from __future__ import annotations

import asyncio
import json

from bat_telegram import incident_publisher as ip
from bat_telegram.bots.jagran.ledger import summarize_day


def test_kavach_blocks_jagran_until_deployment_confirmed(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "batman_state.json"
    state_path.write_text(json.dumps({"deployment": {"confirmed": False}}), encoding="utf-8")
    monkeypatch.setattr(ip, "_kavach_deployment_confirmed", lambda: False)

    async def _fake_jagran(_text: str) -> bool:
        return True

    monkeypatch.setattr(ip, "_send_to_jagran", _fake_jagran)
    jagran_calls: list[str] = []

    async def _track_jagran(text: str) -> bool:
        jagran_calls.append(text)
        return True

    monkeypatch.setattr(ip, "_send_to_jagran", _track_jagran)

    with ip._INCIDENTS_LOCK:
        ip._ACTIVE_INCIDENTS.clear()

    asyncio.run(
        ip.publish_incident(
            source="kavach",
            scenario="order_rejection",
            severity="critical",
            category="order",
            title="Order rejected",
            error_message="margin",
            next_action="Add funds",
            send_to_source=False,
        )
    )
    assert jagran_calls == []

    monkeypatch.setattr(ip, "_kavach_deployment_confirmed", lambda: True)
    asyncio.run(
        ip.publish_incident(
            source="kavach",
            scenario="order_rejection",
            severity="critical",
            category="order",
            title="Order rejected after confirm",
            error_message="margin short",
            next_action="Add funds",
            send_to_source=False,
        )
    )
    assert len(jagran_calls) == 1


def test_summarize_day_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "bat_telegram.bots.jagran.ledger._ledger_dir",
        lambda: tmp_path,
    )
    summary = summarize_day()
    assert summary["triggered"] == 0
    assert summary["open_incident_ids"] == []
