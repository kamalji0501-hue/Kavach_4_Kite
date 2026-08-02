"""Tests for incident publishing, Jagran routing, and daily incident ledger export."""

from __future__ import annotations

import asyncio

import pandas as pd

from bat_telegram import incident_publisher as ip


def test_can_route_to_jagran_supports_wildcard_patterns() -> None:
    assert ip._can_route_to_jagran("main", "module_offline_ato_protection") is True
    assert ip._can_route_to_jagran("main", "heartbeat_loop_error") is True
    assert ip._can_route_to_jagran("main", "unknown_main_scenario") is False


def test_incident_ledger_writes_daily_csv_and_xlsx(tmp_path, monkeypatch) -> None:
    ledger_dir = tmp_path / "incident_ledger"
    monkeypatch.setattr(ip, "_INCIDENT_LEDGER_DIR", ledger_dir)

    async def _fake_send_to_jagran(_text: str) -> bool:
        return False

    monkeypatch.setattr(ip, "_send_to_jagran", _fake_send_to_jagran)

    with ip._INCIDENTS_LOCK:
        ip._ACTIVE_INCIDENTS.clear()

    asyncio.run(
        ip.publish_incident(
            source="main",
            scenario="module_offline_position_monitor",
            severity="major",
            category="runtime",
            title="Module offline",
            error_message="position_monitor crashed",
            next_action="Restart the module.",
            send_to_source=False,
        )
    )

    asyncio.run(
        ip.resolve_incident(
            source="main",
            scenario="module_offline_position_monitor",
            resolution_message="position_monitor recovered.",
            send_to_source=False,
        )
    )

    csv_files = list(ledger_dir.glob("incident_ledger_*.csv"))
    xlsx_files = list(ledger_dir.glob("incident_ledger_*.xlsx"))

    assert len(csv_files) == 1
    assert len(xlsx_files) <= 1

    df = pd.read_csv(csv_files[0])
    assert set(df["event_type"]) == {"incident", "recovery"}
    assert "module_offline_position_monitor" in set(df["scenario"])
    assert "main" in {str(v).lower() for v in set(df["source"])}

    if xlsx_files:
        xdf = pd.read_excel(xlsx_files[0], sheet_name="Combined")
        assert len(xdf) == 2


def test_export_retry_stops_after_max_attempts(tmp_path, monkeypatch) -> None:
    ledger_dir = tmp_path / "incident_ledger"
    monkeypatch.setattr(ip, "_INCIDENT_LEDGER_DIR", ledger_dir)

    params = {
        "enabled": False,
        "dedup_window_seconds": 0,
        "still_failing_interval_seconds": 0,
        "send_recovery": True,
        "ledger_write_csv": True,
        "ledger_export_excel": True,
        "ledger_retry_interval_seconds": -1,
        "ledger_max_export_retries": 3,
    }
    monkeypatch.setattr(ip, "_load_jagran_params", lambda: params)

    attempts = {"count": 0}

    def _always_fail_export(_csv_path, _xlsx_path) -> None:
        attempts["count"] += 1
        raise OSError("simulated lock")

    monkeypatch.setattr(ip, "_try_export_workbook", _always_fail_export)

    with ip._INCIDENTS_LOCK:
        ip._ACTIVE_INCIDENTS.clear()
    with ip._LEDGER_LOCK:
        ip._EXPORT_RETRY_STATE.clear()

    for idx in range(5):
        asyncio.run(
            ip.publish_incident(
                source="main",
                scenario=f"heartbeat_loop_error_{idx}",
                severity="critical",
                category="runtime",
                title="Heartbeat failed",
                error_message="simulated",
                next_action="check",
                send_to_source=False,
            )
        )

    # Retry must cap at configured max (3) despite 5 publish calls.
    assert attempts["count"] == 3

    stream_files = list(ledger_dir.glob("incident_ledger_*.log"))
    assert len(stream_files) == 1


def test_send_to_jagran_retries_after_rate_limit(monkeypatch) -> None:
    class RetryAfter(Exception):
        def __init__(self, retry_after: float) -> None:
            super().__init__("retry later")
            self.retry_after = retry_after

    calls = {"count": 0}

    class FakeBot:
        async def send_message(self, **kwargs):
            del kwargs
            calls["count"] += 1
            if calls["count"] == 1:
                raise RetryAfter(0)

    class FakeCfg:
        bot_token = "token"
        chat_id = "12345"

    monkeypatch.setattr(ip, "_JAGRAN_TOKEN_PATH", __import__("pathlib").Path(__file__))
    monkeypatch.setattr("bat_telegram.incident_publisher.Bot", lambda token: FakeBot())
    monkeypatch.setattr("bat_telegram.loader.load_bot_config", lambda *a, **kw: FakeCfg())

    ok = asyncio.run(ip._send_to_jagran("hello"))
    assert ok is True
    assert calls["count"] == 2
