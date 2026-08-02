"""Shadow fill premiums must stamp avg_price for SARANSH Buy/Sell columns."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backtest_engine.shadow.order_ledger import (
    _apply_fill_to_book,
    _resolve_shadow_fill_price,
    _uat_fallback_premium,
)

_FIXTURE = {
    "expiry_date": "2026-07-28",
    "legs": [
        {
            "role_hint": "pe_sell",
            "strike": 23950,
            "type": "PE",
            "side": "SELL",
            "lots": 2,
            "avg_price": 1,
        },
        {
            "role_hint": "pe_buy",
            "strike": 24000,
            "type": "PE",
            "side": "BUY",
            "lots": 1,
            "avg_price": 1,
        },
        {
            "role_hint": "ce_buy",
            "strike": 23950,
            "type": "CE",
            "side": "BUY",
            "lots": 1,
            "avg_price": 1,
        },
        {
            "role_hint": "ce_sell",
            "strike": 24000,
            "type": "CE",
            "side": "SELL",
            "lots": 2,
            "avg_price": 1,
        },
    ],
}


def test_uat_fallback_premium_otm_pe() -> None:
    px = _uat_fallback_premium("NIFTY-Jul2026-23900-PE", spot=24000.0)
    assert px >= 1.0


def test_resolve_shadow_fill_uses_broker_quote_api(monkeypatch, tmp_path: Path) -> None:
    """Broker.get_nifty_option_ltps alone must be enough (no TokenStore file)."""
    calls: list[tuple] = []

    def _quote(legs, expiry_date=None):
        calls.append((legs, expiry_date))
        return {(23900, "PE"): 42.5}

    broker = SimpleNamespace(
        _client_code="1106926362",
        _access_token="jwt-test",
        _root=tmp_path,
        get_nifty_option_ltps=_quote,
    )
    monkeypatch.setattr("core.uat_positions.load_positions_fixture", lambda root: _FIXTURE)
    monkeypatch.setattr(
        "core.nifty_option_expiry.fixture_expiry_date",
        lambda fix: __import__("datetime").date(2026, 7, 28),
    )

    price = _resolve_shadow_fill_price(broker, "NIFTY-Jul2026-23900-PE")
    assert price == 42.5
    assert calls


def test_apply_fill_stamps_avg_price_when_quote_ok(monkeypatch, tmp_path: Path) -> None:
    import pandas as pd

    broker = SimpleNamespace(
        _client_code="1106926362",
        _access_token="jwt-test",
        _root=tmp_path,
        _positions_df=pd.DataFrame(),
        get_nifty_option_ltps=lambda legs, expiry_date=None: {(23900, "PE"): 33.25},
    )
    monkeypatch.setattr("core.uat_positions.load_positions_fixture", lambda root: _FIXTURE)
    monkeypatch.setattr(
        "core.nifty_option_expiry.fixture_expiry_date",
        lambda fix: __import__("datetime").date(2026, 7, 28),
    )
    monkeypatch.setattr(
        "backtest_engine.shadow.position_book.apply_virtual_fill",
        lambda df, **kw: df,
    )

    entry: dict = {"order_id": "SHADOW-00099"}
    _apply_fill_to_book(
        broker,
        "NIFTY-Jul2026-23900-PE",
        65,
        "BUY",
        order_entry=entry,
    )
    assert entry["avg_price"] == 33.25
