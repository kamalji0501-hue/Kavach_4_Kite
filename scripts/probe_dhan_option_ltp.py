"""Read-only probe: JWT, NIFTY LTP, option chain / option LTP (no secrets printed)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    tok_path = ROOT / "data" / "access_token.json"
    if not tok_path.exists():
        print("JWT: MISSING access_token.json — refresh via DRISHTI")
        return 1

    tok = json.loads(tok_path.read_text(encoding="utf-8"))
    token = (tok.get("access_token") or tok.get("token") or "").strip()
    saved = tok.get("saved_at") or tok.get("timestamp") or "unknown"
    print(f"JWT file: present saved_at={saved}")

    from dotenv import dotenv_values

    env = dotenv_values(ROOT / "config" / ".env")
    cc = (env.get("DHAN_CLIENT_CODE") or "").strip()
    print(f"client_id: {'ok' if cc else 'MISSING'}")

    headers = {"access-token": token, "client-id": cc}
    try:
        r = httpx.get("https://api.dhan.co/v2/fundlimit", headers=headers, timeout=15)
        print(f"fundlimit: HTTP {r.status_code}")
    except Exception as exc:
        print(f"fundlimit error: {exc}")

    from core.nifty_ltp import fetch_nifty_ltp_rest

    try:
        n = fetch_nifty_ltp_rest(cc, token)
        print(f"NIFTY REST marketfeed: OK ltp={n:.2f}")
    except Exception as exc:
        print(f"NIFTY REST: FAIL {exc}")

    from core.broker import BatmanBroker

    try:
        broker = BatmanBroker.connect_with_token(cc, token)
        print("BatmanBroker: connected")
    except Exception as exc:
        print(f"BatmanBroker: FAIL {exc}")
        return 2

    try:
        print(f"get_ltp NIFTY: {broker.get_ltp(['NIFTY'])}")
    except Exception as exc:
        print(f"get_ltp NIFTY: FAIL {exc}")

    fixture = None
    try:
        from core.uat_positions import load_positions_fixture

        fixture = load_positions_fixture(ROOT)
        print(f"fixture: expiry={fixture.get('expiry_date')} legs={len(fixture.get('legs', []))}")
    except Exception as exc:
        print(f"fixture: none ({exc})")

    from core.nifty_option_expiry import fixture_expiry_date, legs_from_fixture

    if fixture:
        target_exp = fixture_expiry_date(fixture)
        leg_pairs = legs_from_fixture(fixture)
        from backtest_engine.resolver.instrument_master import (
            load_instrument_master,
            resolve_nifty_option,
        )

        master = load_instrument_master()
        sec_ids: list[int] = []
        for strike, opt in leg_pairs:
            inst = resolve_nifty_option(
                strike=strike, option_type=opt, expiry_date=target_exp, master=master
            )
            print(f"resolved {strike}{opt}: symbol={inst.trading_symbol} id={inst.security_id}")
            sec_ids.append(int(inst.security_id))
            try:
                print(f"get_ltp [{inst.trading_symbol}]: {broker.get_ltp([inst.trading_symbol])}")
            except Exception as exc:
                print(f"get_ltp Tradehull symbol: FAIL {exc}")

        try:
            quotes = broker.get_fno_ltp_by_security_ids(sec_ids)
            print(f"marketfeed NSE_FNO LTP ({len(quotes)}): {quotes}")
        except Exception as exc:
            print(f"marketfeed NSE_FNO: FAIL {exc}")

        try:
            by_strike = broker.get_nifty_option_ltps(leg_pairs, expiry_date=target_exp)
            print(f"get_nifty_option_ltps ({len(by_strike)}): {by_strike}")
        except Exception as exc:
            print(f"get_nifty_option_ltps: FAIL {exc}")

        from core.uat_position_enrich import try_option_chain_premiums

        try:
            m = try_option_chain_premiums(
                broker,
                target_expiry=target_exp,
                strikes=sorted({s for s, _ in leg_pairs}),
            )
            print(f"chain premiums ({len(m)}): {m}")
        except Exception as exc:
            print(f"try_option_chain_premiums: FAIL {exc}")
    else:
        print("Skip option leg probe — no uat/deployed_positions/positions.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
