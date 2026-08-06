from __future__ import annotations

import csv
import json
from datetime import date


def _write_deployment(tmp_path, *, ce_be=99999, pe_be=11111):
    """Deployment fixture. risk.break_even is legacy and ignored by RATRIPAL strike math."""
    deployment = {
        "file_name": "batman_test.json",
        "calendar": {
            "deploy_date": "2026-04-22",
            "expiry_date": "2026-04-28",
            "effective_working_days": [
                "2026-04-22",
                "2026-04-23",
                "2026-04-24",
                "2026-04-27",
                "2026-04-28",
            ],
        },
        "positions": {
            "ce_sell": {"symbol": "NIFTY25APR24750CE", "strike": 24750, "qty": -130},
            "ce_buy": {"symbol": "NIFTY25APR24700CE", "strike": 24700, "qty": 65},
            "pe_sell": {"symbol": "NIFTY25APR24150PE", "strike": 24150, "qty": -130},
            "pe_buy": {"symbol": "NIFTY25APR24300PE", "strike": 24300, "qty": 65},
        },
        "risk": {
            "break_even": {
                "ce": ce_be,
                "pe": pe_be,
                "skipped": False,
            }
        },
    }
    path = tmp_path / "batman_test.json"
    path.write_text(json.dumps(deployment), encoding="utf-8")
    return path, deployment


def test_ratripal_calculates_working_day_dte(mock_broker, config, state, event_bus, tmp_path):
    from modules.ratripal import Ratripal

    _, deployment = _write_deployment(tmp_path)
    mod = Ratripal(mock_broker, config, state, event_bus)

    assert mod._calculate_dte(deployment, date(2026, 4, 27)) == 1
    assert mod._calculate_dte(deployment, date(2026, 4, 28)) == 0


def test_ratripal_fixed_break_even_from_sell_legs(mock_broker, config, state, event_bus, tmp_path):
    from modules.ratripal import Ratripal

    mod = Ratripal(mock_broker, config, state, event_bus)
    assert mod._fixed_break_even("CE", 24750) == 24950  # +200
    assert mod._fixed_break_even("PE", 24150) == 23950  # -200
    assert mod._fixed_break_even("CE", 0) is None


def test_ratripal_white_zone_uses_standard_break_even(
    mock_broker, config, state, event_bus, tmp_path
):
    from modules.ratripal import Ratripal

    # Legacy BE values must be ignored — fixed sell±200 wins.
    _, deployment = _write_deployment(tmp_path, ce_be=99999, pe_be=11111)
    mod = Ratripal(mock_broker, config, state, event_bus)

    plans = mod._build_plans(deployment, spot=24550.0, dte=3)
    ce_plan = next(plan for plan in plans if plan.side == "CE")
    pe_plan = next(plan for plan in plans if plan.side == "PE")

    assert ce_plan.action == "standard_break_even"
    assert ce_plan.break_even == 24950
    assert ce_plan.strike == 24950
    assert pe_plan.action == "standard_break_even"
    assert pe_plan.break_even == 23950
    assert pe_plan.strike == 23950


def test_ratripal_color_zone_depth_from_fixed_be(mock_broker, config, state, event_bus, tmp_path):
    from modules.ratripal import Ratripal

    _, deployment = _write_deployment(tmp_path, ce_be=20000, pe_be=20000)
    mod = Ratripal(mock_broker, config, state, event_bus)

    # DTE=3 CE boxes: Orange then Green. Spot 24700 → Orange (2 strikes inside fixed BE).
    plans = mod._build_plans(deployment, spot=24700.0, dte=3)
    ce_plan = next(plan for plan in plans if plan.side == "CE")

    assert ce_plan.state == "Orange"
    assert ce_plan.break_even == 24950
    assert ce_plan.action == "orange_inside"
    # 24950 - 2*50 = 24850; clamp vs sell+50 keeps 24850
    assert ce_plan.strike == 24850


def test_ratripal_breach_without_ato_buys_breach_protection(
    mock_broker, config, state, event_bus, tmp_path
):
    from modules.ratripal import Ratripal

    _, deployment = _write_deployment(tmp_path)
    mod = Ratripal(mock_broker, config, state, event_bus)

    plans = mod._build_plans(deployment, spot=24780.0, dte=1)
    ce_plan = next(plan for plan in plans if plan.side == "CE")

    assert ce_plan.state == "Breach"
    assert ce_plan.action == "breach_protect"
    assert ce_plan.strike == 24800
    assert ce_plan.symbol == "NIFTY25APR24800CE"


def test_ratripal_execute_plan_writes_verified_handoff(
    mock_broker, config, state, event_bus, tmp_path
):
    import modules.ratripal as ratripal_mod
    from modules.ratripal import Ratripal

    path, deployment = _write_deployment(tmp_path)
    state.set("deployment.file", str(path), save=False)

    handoff_path = tmp_path / "aditya_handoff.csv"
    ratripal_mod._HANDOFF_PATH = handoff_path

    mod = Ratripal(mock_broker, config, state, event_bus)
    plan = mod._build_plans(deployment, spot=24550.0, dte=1)[0]

    assert mod._execute_plan(plan, deployment, 1, 24550.0, "req-1") is True
    assert handoff_path.exists()
    assert state.get("aditya.handoff_file") == str(handoff_path)

    with open(handoff_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 1
    assert rows[0]["side"] == "CE"
    assert rows[0]["status"] == "verified_buy"
    assert rows[0]["symbol"] == plan.symbol
