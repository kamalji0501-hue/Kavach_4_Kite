"""SARANSH summary economy profile section (Q58)."""

from __future__ import annotations

from collections import Counter

from bat_telegram.bots.saransh import bot as saransh_bot


def _base_payload(**overrides):
    payload = {
        "generated_at": "10:00 IST, 20 Jun 2026",
        "deployment_file": "batman_test.json",
        "algo_paused": False,
        "economy_profile": False,
        "custom_protect_strike": False,
        "ce_protect_mode": "AUTO",
        "pe_protect_mode": "AUTO",
        "total_orders": 0,
        "total_ato_orders": 0,
        "impact_points": 0.0,
        "total_pnl": 0.0,
        "deployed_lots": 1,
        "one_lot_equivalent": 0.0,
        "pnl_pct": 0.0,
        "action_counter": Counter(),
        "reason_counter": Counter(),
        "density_counter": Counter(),
        "strike_context_counter": Counter(),
        "telemetry_missing": False,
        "telemetry_empty": True,
        "token_addendum": "Token: ok",
    }
    payload.update(overrides)
    return payload


def test_render_summary_omits_economy_profile_section():
    """Economy/profile block was removed from the compact summary (per UX ask)."""
    text = saransh_bot._render_summary(
        _base_payload(
            economy_profile=True,
            custom_protect_strike=True,
            ce_protect_mode="CUSTOM",
        )
    )
    assert "Economy profile" not in text
    assert "custom protect" not in text


def test_render_summary_compact_core_sections():
    """Summary keeps header, P&L (Running only), ATO trips and Orders."""
    text = saransh_bot._render_summary(_base_payload(total_pnl=0.0, total_orders=4))
    assert "SARANSH — Daily Summary" in text
    assert "Running: <code>Rs +0.00</code>" in text
    assert "ATO round trips today:" in text
    assert "Orders today:</b> 4" in text
    # Trimmed fields must not appear.
    assert "One-lot" not in text
    assert "Return:" not in text
    assert "Token" not in text
    assert "UAT shadow PnL" not in text
