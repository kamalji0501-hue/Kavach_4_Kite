"""Tests for option LTP audit logging + watchlist resolution."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.option_ltp_audit import append_option_ltp_log, format_option_ltp_log_line
from core.option_ltp_watchlist import build_option_watchlist


def test_format_option_ltp_log_line_orders_roles() -> None:
    now = datetime(2026, 7, 23, 15, 29, 53, 399000, tzinfo=ZoneInfo("Asia/Kolkata"))
    line = format_option_ltp_log_line(
        now,
        {"ce_sell": 33.1, "pe_sell": 48.05, "ce_protect": 5.85},
    )
    assert line.startswith("15:29:53.399 | ")
    assert "pe_sell=48.05" in line
    assert "ce_sell=33.10" in line
    assert "ce_protect=5.85" in line
    # pe_sell before ce_sell
    assert line.index("pe_sell=") < line.index("ce_sell=")


def test_append_option_ltp_log_writes_daily_file(tmp_path: Path) -> None:
    now = datetime(2026, 7, 23, 11, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    path = append_option_ltp_log(tmp_path, now, {"pe_buy": 12.5})
    assert path.name == "option_ltp_20260723.log"
    text = path.read_text(encoding="utf-8")
    assert "pe_buy=12.50" in text


def test_build_option_watchlist_from_deployment(tmp_path: Path, monkeypatch) -> None:
    dep_dir = tmp_path / "deployments"
    dep_dir.mkdir()
    payload = {
        "positions": {
            "pe_sell": {
                "symbol": "NIFTY-Jul2026-23700-PE",
                "strike": 23700,
                "opt_type": "PE",
                "instrument_token": "63926",
                "expiry": "28 Jul 2026",
            },
            "ce_sell": {
                "symbol": "NIFTY-Jul2026-24400-CE",
                "strike": 24400,
                "opt_type": "CE",
                "instrument_token": "63955",
                "expiry": "28 Jul 2026",
            },
            "pe_buy": None,
            "ce_buy": None,
        },
        "ato": {
            "pe_protect_symbol": "NIFTY-Jul2026-23550-PE",
            "pe_protect_strike": 23550,
            "ce_protect_symbol": "NIFTY-Jul2026-24600-CE",
            "ce_protect_strike": 24600,
        },
    }
    (dep_dir / "batman_2026-07-23_13-30.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "core.option_ltp_watchlist.deployments_dir", lambda root=None: dep_dir
    )
    monkeypatch.setattr(
        "core.option_ltp_watchlist.state_path", lambda root=None: tmp_path / "missing.json"
    )

    # Stub protect resolve to avoid instrument master network/disk.
    def _fake_resolve(*, strike, option_type, expiry):
        class _I:
            security_id = str(100000 + int(strike) + (1 if option_type == "CE" else 0))

        return _I()

    monkeypatch.setattr(
        "core.option_ltp_watchlist._resolve_protect_id",
        lambda **kw: int(
            _fake_resolve(
                strike=kw["strike"], option_type=kw["option_type"], expiry=kw["expiry"]
            ).security_id
        ),
    )

    watch = build_option_watchlist(tmp_path)
    roles = {i.role for i in watch.items}
    assert "pe_sell" in roles and "ce_sell" in roles
    assert "pe_protect" in roles and "ce_protect" in roles
    assert watch.source.startswith("deployment:")
