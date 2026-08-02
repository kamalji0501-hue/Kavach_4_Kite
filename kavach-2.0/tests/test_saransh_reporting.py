"""SARANSH ATO Cycle rendering from JSONL feed."""

from __future__ import annotations

from pathlib import Path

from core.ato_cycle_feed import record_ato_buy, record_ato_cycle_complete
from core.saransh_reporting import (
    load_live_ato_status,
    load_today_completed_cycles,
    render_ato_cycle_messages,
)


def _uat_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("BATMAN_MODE", "uat")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "batman_mode.json").write_text(
        '{"mode": "uat", "modes": {"uat": {"data_root": "data/uat"}}}',
        encoding="utf-8",
    )
    return tmp_path


def test_render_ato_cycle_compact_table(tmp_path: Path, monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    root = _uat_root(tmp_path, monkeypatch)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    ts = f"{today} 10:00:00 IST"
    record_ato_buy(
        side="CE",
        sell_strike=24500,
        buy_nifty_ltp=100.0,
        lots=1.0,
        timestamp_ist=ts,
        deployment_file="batman.json",
        root=root,
        protect_strike=25000,
    )
    record_ato_cycle_complete(
        side="CE",
        sell_strike=24500,
        buy_nifty_ltp=100.0,
        sell_nifty_ltp=97.0,
        lots=1.0,
        timestamp_ist=f"{today} 10:05:00 IST",
        deployment_file="batman.json",
        root=root,
        protect_strike=25000,
        buy_option_premium=6.15,
        sell_option_premium=6.10,
    )
    cycles = load_today_completed_cycles(root=root)
    assert len(cycles) == 1
    assert cycles[0].point_impact == -3.0
    assert cycles[0].protect_strike == 25000
    assert cycles[0].buy_option_premium == 6.15
    assert cycles[0].sell_option_premium == 6.10
    assert cycles[0].premium_diff == -0.05
    msgs = render_ato_cycle_messages(root=root, orders_today=2, orders_alltime=10)
    text = msgs[0]
    assert "ATO Cycle" in text
    assert "Round trips today:</b> 1" in text
    assert "Today:</b> 2" in text
    assert "All-time:</b> 10" in text
    # Net impact is the ATO premium difference (sell − buy), not NIFTY spot.
    assert "Net point impact:</b> <code>-0.05</code>" in text
    # Buy/Sell columns show the ATO option premium (6.15 / 6.10).
    assert "6.15" in text
    assert "6.10" in text
    # ATO (protect) strike is shown, not the sell strike.
    assert "25000" in text
    assert "24500" not in text


def test_synthetic_rows_without_deployment_are_ignored(tmp_path: Path, monkeypatch) -> None:
    """Feed rows with a blank deployment_file (test/synthetic) are never counted."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    root = _uat_root(tmp_path, monkeypatch)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")

    # Synthetic injection: empty deployment_file.
    record_ato_buy(
        side="CE",
        sell_strike=25500,
        buy_nifty_ltp=25505.0,
        lots=1.0,
        timestamp_ist=f"{today} 11:48:00 IST",
        deployment_file="",
        root=root,
        protect_strike=25550,
    )
    record_ato_cycle_complete(
        side="CE",
        sell_strike=25500,
        buy_nifty_ltp=25505.0,
        sell_nifty_ltp=25505.0,
        lots=1.0,
        timestamp_ist=f"{today} 11:48:01 IST",
        deployment_file="",
        root=root,
        protect_strike=25550,
    )

    assert load_today_completed_cycles(root=root) == []
    text = render_ato_cycle_messages(root=root)[0]
    assert "Round trips today:</b> 0" in text
    assert "No completed cycles today." in text
    # Synthetic holding must not be surfaced (both sides read "not holding").
    assert "CE:</b> not holding ATO" in text
    assert "🟡" not in text
    assert "25550" not in text


def _write_state(root: Path, ato: dict) -> None:
    import json

    from core.batman_mode import state_path

    sp = state_path(root)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"ato": ato}), encoding="utf-8")


def test_live_ato_status_reflects_kavach_trigger(tmp_path: Path, monkeypatch) -> None:
    """SARANSH must mirror KAVACH2's ATO trigger even with no cycle-feed row."""
    root = _uat_root(tmp_path, monkeypatch)
    _write_state(
        root,
        {
            "ce_triggered": True,
            "ce_ato_active": False,
            "ce_protect_strike": 25000,
            "pe_triggered": False,
            "pe_ato_active": False,
            "pe_protect_strike": 23500,
        },
    )

    live = load_live_ato_status(root=root)
    assert live["CE"]["triggered"] is True
    assert live["CE"]["protect_strike"] == 25000

    text = render_ato_cycle_messages(root=root)[0]
    # CE reflects the live trigger with the ATO (protect) strike; PE stays idle.
    assert "CE:</b> ATO triggered — protect <b>25000</b>" in text
    assert "PE:</b> not holding ATO" in text


def test_live_ato_status_active_holding(tmp_path: Path, monkeypatch) -> None:
    root = _uat_root(tmp_path, monkeypatch)
    _write_state(
        root,
        {
            "pe_triggered": True,
            "pe_ato_active": True,
            "pe_protect_strike": 23500,
        },
    )
    text = render_ato_cycle_messages(root=root)[0]
    assert "PE:</b> holding ATO — protect <b>23500</b>" in text
