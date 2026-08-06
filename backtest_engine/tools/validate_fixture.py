#!/usr/bin/env python3
"""
P0 — Validate Sensibull fixture → Dhan symbols (production-shaped output).

Uses:
  - JWT from data/access_token.json (same as DRISHTI / KAVACH)
  - Dhan instrument master for securityId + tradingSymbol (authoritative)
  - Optional Tradehull option chain cross-check
  - core.positions.filter_nifty_positions, build_ato_protect_symbol
  - core.position_scope.validate_side_ratio

Run:
  python backtest_engine/tools/validate_fixture.py
  python backtest_engine/tools/validate_fixture.py --fixture path/to.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_DEFAULT_FIXTURE = ROOT / "uat" / "deployed_positions" / "positions.json"
_FALLBACK_FIXTURE = (
    ROOT / "backtest_engine" / "fixtures" / "sensibull" / "jun9_2026_sensibull.json"
)
_RESOLVED_DIR = ROOT / "backtest_engine" / "fixtures" / "resolved"
_NIFTY_LOT_SIZE = 65
_ATO_STEP = 50


def _load_fixture(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _jwt_gate() -> tuple[str, str, Any]:
    from dotenv import dotenv_values

    from core.broker import BatmanBroker
    from core.nifty_ltp import validate_dhan_access_token
    from core.token_store import TokenStore

    env = dotenv_values(ROOT / "config" / ".env")
    client_code = (env.get("DHAN_CLIENT_CODE") or "").strip()
    store = TokenStore(path=ROOT / "data" / "access_token.json")
    token, saved_at = store.load()

    print("=== Shadow P0 — JWT & instrument resolve ===\n")
    print(f"  client_code : {client_code or '(missing)'}")
    print(f"  dhan_jwt    : {'present' if token else 'missing'}")
    print(f"  saved_at    : {saved_at}")
    print(f"  age_hours   : {store.token_age_hours():.2f}")
    print(f"  expired     : {store.is_expired()}\n")

    if not client_code or not token:
        print("BLOCKED: Send a fresh Dhan JWT to DRISHTI first.")
        raise SystemExit(1)

    ok, err = validate_dhan_access_token(client_code, token)
    if not ok:
        print(f"BLOCKED: Dhan rejected JWT — {err}")
        print("Update token via DRISHTI, then re-run.")
        raise SystemExit(1)

    print("  JWT validate : OK (Dhan fund-limit / auth probe)\n")
    broker = BatmanBroker.connect_with_token(client_code, token)
    return client_code, token, broker


def _net_qty(side: str, lots: int) -> int:
    qty = lots * _NIFTY_LOT_SIZE
    return qty if side.upper() == "BUY" else -qty


def _expiry_date_from_fixture(data: dict[str, Any]) -> date:
    if data.get("expiry_date"):
        return date.fromisoformat(str(data["expiry_date"]))
    from backtest_engine.resolver.instrument_master import _parse_expiry_date

    return _parse_expiry_date(str(data["expiry_label"]))


def _role_positions(
    fixture: dict[str, Any],
    resolved_by_index: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build sell-side deployment-shaped dicts (buys chosen later in Register)."""
    out: dict[str, dict[str, Any]] = {}
    for i, leg in enumerate(fixture["legs"]):
        side = str(leg["side"]).upper()
        opt = str(leg["type"]).upper()
        if side != "SELL":
            continue
        role = "pe_sell" if opt == "PE" else "ce_sell"
        r = resolved_by_index[i]
        sym = r["trading_symbol"]
        if sym.startswith("NIFTY-"):
            expiry_label = sym.split("-")[1]
        else:
            import re

            m = re.search(r"^NIFTY(\d{2}[A-Z]{3})", sym)
            expiry_label = m.group(1) if m else str(fixture.get("expiry_label", ""))

        out[role] = {
            "symbol": sym,
            "strike": int(leg["strike"]),
            "expiry": expiry_label,
            "qty": abs(_net_qty(leg["side"], int(leg["lots"]))),
            "avg_price": float(leg["avg_price"]),
            "instrument_token": r["security_id"],
            "side": "SELL",
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Sensibull fixture (P0)")
    parser.add_argument("--fixture", type=Path, default=_DEFAULT_FIXTURE)
    parser.add_argument("--ato-step", type=int, default=_ATO_STEP)
    parser.add_argument("--skip-chain", action="store_true", help="Skip option chain cross-check")
    args = parser.parse_args()

    fixture_path = args.fixture.resolve()
    if not fixture_path.is_file():
        print(f"Fixture not found: {fixture_path}")
        if fixture_path == _DEFAULT_FIXTURE.resolve():
            print("  Paste Sensibull screenshot in uat/deployed_positions/ and create positions.json")
        return 1

    fixture = _load_fixture(fixture_path)
    from core.uat_chat_positions import UATChatPositionsError, validate_fixture

    try:
        validate_fixture(fixture)
    except UATChatPositionsError as exc:
        print(f"FAIL: chat fixture schema — {exc}")
        return 1

    fixture_expiry = _expiry_date_from_fixture(fixture)
    raw_spot = fixture.get("spot_at_capture", 0)
    spot = float(raw_spot) if raw_spot is not None else 0.0

    from backtest_engine.resolver.instrument_master import (
        load_instrument_master,
        resolve_fixture_trading_expiry,
        resolve_nifty_option,
        resolved_to_dict,
    )
    from backtest_engine.resolver.option_chain_resolver import try_option_chain_cross_check
    from core.positions import build_ato_protect_symbol, filter_nifty_positions, format_position_summary

    _, _, broker = _jwt_gate()

    master = load_instrument_master()
    expiry, rolled = resolve_fixture_trading_expiry(
        fixture_expiry,
        fixture["legs"],
        master=master,
    )
    resolved_by_index: list[dict[str, Any]] = []
    broker_rows: list[dict[str, Any]] = []
    strikes_for_chain: list[int] = []

    print(f"  fixture      : {fixture_path.name}")
    if rolled:
        print(
            f"  expiry_date  : {expiry.isoformat()} "
            f"(rolled from fixture {fixture_expiry.isoformat()})"
        )
    else:
        print(f"  expiry_date  : {expiry.isoformat()} (from fixture values)")
    print(f"  spot_capture : {spot:,.2f}")
    print(f"  leg_count    : {len(fixture['legs'])} (6 BUY + 2 SELL; Core BUY picked in Register)\n")

    for leg in fixture["legs"]:
        strike = int(leg["strike"])
        opt = str(leg["type"]).upper()
        strikes_for_chain.append(strike)

        inst = resolve_nifty_option(
            strike=strike,
            option_type=opt,
            expiry_date=expiry,
            master=master,
        )
        net_qty = _net_qty(str(leg["side"]), int(leg["lots"]))
        resolved_by_index.append(resolved_to_dict(inst))
        broker_rows.append(inst.to_broker_row(net_qty=net_qty, avg_price=float(leg["avg_price"])))

    import pandas as pd

    positions_df = pd.DataFrame(broker_rows)
    filtered = filter_nifty_positions(positions_df)

    print("--- Positions (production filter_nifty_positions) ---\n")
    print(format_position_summary(filtered).replace("₹", "Rs "))
    print()

    roles = _role_positions(fixture, resolved_by_index)
    pe_sell = roles.get("pe_sell")
    ce_sell = roles.get("ce_sell")
    if not pe_sell or not ce_sell:
        print("FAIL: need exactly one PE SELL and one CE SELL in the book")
        return 1

    print("--- Ratio check ---")
    print("  SKIPPED — Core PE/CE BUY are chosen in Register (book has multiple BUY candidates).")
    print()

    pe_ato_strike = pe_sell["strike"] - args.ato_step
    ce_ato_strike = ce_sell["strike"] + args.ato_step
    pe_ato_sym = build_ato_protect_symbol(pe_sell["symbol"], pe_ato_strike, "PE")
    ce_ato_sym = build_ato_protect_symbol(ce_sell["symbol"], ce_ato_strike, "CE")

    pe_inst = resolve_nifty_option(strike=pe_ato_strike, option_type="PE", expiry_date=expiry, master=master)
    ce_inst = resolve_nifty_option(strike=ce_ato_strike, option_type="CE", expiry_date=expiry, master=master)

    print("--- ATO protect legs (NOT in shadow book until simulated BUY) ---")
    print(f"  PE sell {pe_sell['strike']} -> protect {pe_ato_strike}  {pe_ato_sym}  securityId={pe_inst.security_id}")
    print(f"  CE sell {ce_sell['strike']} -> protect {ce_ato_strike}  {ce_ato_sym}  securityId={ce_inst.security_id}")
    print()
    print("--- ATO triggers (buffer 0, live NIFTY decides timing) ---")
    print(f"  PE entry when NIFTY <= {pe_sell['strike']:,}  (margin now: {spot - pe_sell['strike']:,.2f} pts)")
    print(f"  CE entry when NIFTY >= {ce_sell['strike']:,}  (margin now: {ce_sell['strike'] - spot:,.2f} pts)")
    print()

    chain_report: dict[str, Any] = {"skipped": True}
    if not args.skip_chain:
        print("--- Option chain cross-check (Tradehull; may be empty after hours) ---")
        chain_report = try_option_chain_cross_check(
            broker,
            target_expiry=expiry,
            strikes=strikes_for_chain + [pe_ato_strike, ce_ato_strike],
        )
        print(f"  chain_available : {chain_report.get('chain_available')}")
        for note in chain_report.get("notes", []):
            print(f"  note            : {note}")
        print()

    report = {
        "schema_version": "shadow_p0_v2_8leg",
        "fixture": str(fixture_path.relative_to(ROOT)) if fixture_path.is_relative_to(ROOT) else str(fixture_path),
        "expiry_date": expiry.isoformat(),
        "spot_at_capture": spot,
        "lot_size": _NIFTY_LOT_SIZE,
        "jwt_validated": True,
        "leg_count": len(fixture["legs"]),
        "positions_roles_sells": roles,
        "resolved_instruments": resolved_by_index,
        "ato": {
            "ato_step": args.ato_step,
            "pe_protect_symbol": pe_ato_sym,
            "pe_protect_strike": pe_ato_strike,
            "pe_protect_security_id": pe_inst.security_id,
            "ce_protect_symbol": ce_ato_sym,
            "ce_protect_strike": ce_ato_strike,
            "ce_protect_security_id": ce_inst.security_id,
            "pe_trigger_spot": pe_sell["strike"],
            "ce_trigger_spot": ce_sell["strike"],
        },
        "ratio_checks": {
            "skipped": True,
            "reason": "Core BUY selected in Register from multiple candidates",
        },
        "option_chain_cross_check": chain_report,
        "broker_positions_preview": broker_rows,
        "production_filter_count": len(filtered),
    }

    _RESOLVED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _RESOLVED_DIR / f"{fixture_path.stem}_resolved.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(f"--- Resolved JSON ---\n  {out_path}\n")
    print("P0 PASS — fixture maps to Dhan symbols/securityIds. Ready for shadow book (P1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
