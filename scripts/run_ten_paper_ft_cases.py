#!/usr/bin/env python3
"""Run 10 paper FT-style punches; verify [PAPER TRADE] logs; check bots stay up."""

from __future__ import annotations

import json
import logging
import random
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.batman_mode import data_root, ensure_runtime_layout
from core.bot_logging import configure_bot_logging
from core.dhan_credentials import apply_dhan_secrets_env, dhan_secrets_status
from core.money_audit import audit, audit_paths
from core.order_manager import OrderManager
from core.order_mode import configure_ato_order_sink
from core.paper_trade_logging import PAPER_PREFIX, get_trade_lane, set_trade_lane


def _atm_strikes(nifty: float, n: int = 10) -> list[int]:
    atm = int(round(float(nifty) / 50.0) * 50)
    offsets = [-200, -150, -100, -50, 0, 50, 100, 150, 200, 250]
    random.shuffle(offsets)
    return [atm + off for off in offsets[:n]]


def _fetch_nifty_ltp() -> float:
    log = logging.getLogger("ten_paper_ft")
    try:
        from core.dhan_pin_totp import obtain_access_token_via_pin_totp, pin_totp_env_present
        from core.broker import BatmanBroker
        from core.token_store import TokenStore
        from core.batman_mode import access_token_path

        if pin_totp_env_present(ROOT):
            client, token = obtain_access_token_via_pin_totp()
            TokenStore(path=access_token_path(ROOT)).save(token)
            broker = BatmanBroker.connect_with_token(client, token)
            data = broker.get_ltp(["NIFTY"])
            val = float(next(iter(data.values())))
            if val > 0:
                log.info("NIFTY LTP via PIN/TOTP: %s", val)
                return val
    except Exception as exc:
        log.warning("NIFTY LTP PIN/TOTP path failed: %s", exc)
    try:
        import os
        from core.batman_mode import access_token_path
        from core.broker import BatmanBroker
        from core.token_store import TokenStore

        apply_dhan_secrets_env(ROOT)
        client = (os.environ.get("DHAN_CLIENT_CODE") or "").strip()
        tok, _ = TokenStore(path=access_token_path(ROOT)).load()
        if client and tok:
            broker = BatmanBroker.connect_with_token(client, tok)
            data = broker.get_ltp(["NIFTY"])
            val = float(next(iter(data.values())))
            if val > 0:
                log.info("NIFTY LTP via TokenStore: %s", val)
                return val
    except Exception as exc:
        log.warning("NIFTY LTP token path failed: %s", exc)
    log.warning("Using fallback NIFTY ref 24500 for strike selection")
    return 24500.0


def _bots_alive() -> dict[str, bool]:
    out = subprocess.check_output(["ps", "aux"], text=True)
    return {
        "drishti": "run_drishti.py" in out,
        "kavach2": "run_kavach2.py" in out,
        "jagran": "run_jagran.py" in out,
        "saransh": "run_saransh.py" in out,
    }


def main() -> int:
    import os
    random.seed()
    os.chdir(ROOT)
    # Place Order backend on sys.path for paper OM
    pob = Path("/home/ubuntu/place-order-bot")
    if pob.is_dir() and str(pob) not in sys.path:
        sys.path.insert(0, str(pob))
    ensure_runtime_layout(ROOT)
    apply_dhan_secrets_env(ROOT)
    log_path = configure_bot_logging(workspace_root=ROOT, bot_name="kavach")
    log = logging.getLogger("ten_paper_ft")
    st = dhan_secrets_status(ROOT)
    log.info("dhan secrets ready=%s keys=%s", st.get("pin_totp_ready"), st.get("keys_present"))

    ato_module = SimpleNamespace()
    state = SimpleNamespace(_data={})
    def _set(k, v):
        state._data[k] = v
    def _get(k, default=None):
        return state._data.get(k, default)
    state.set = _set  # type: ignore
    state.get = _get  # type: ignore

    mode = configure_ato_order_sink(
        ato_module, order_mode="paper", workspace_root=ROOT, state=state
    )
    assert mode == "paper"
    set_trade_lane("paper")
    om = getattr(ato_module, "order_manager", None)
    if om is None:
        om = OrderManager(mode="paper", ledger_dir=data_root(ROOT) / "order_manager")

    nifty = _fetch_nifty_ltp()
    # paper OM default LTP for FakeBroker fill pricing
    try:
        om.default_ltp = max(40.0, round(nifty * 0.004, 2))
    except Exception:
        pass

    strikes = _atm_strikes(nifty, 10)
    sides = ["BUY", "SELL", "BUY", "SELL", "BUY", "SELL", "BUY", "SELL", "BUY", "SELL"]
    opts = ["CE", "PE", "CE", "PE", "CE", "PE", "CE", "PE", "CE", "PE"]
    random.shuffle(sides)
    random.shuffle(opts)

    audit("ten_paper_ft.batch.start", mode="paper", nifty=nifty, strikes=strikes, cases=10)
    results = []
    for i in range(10):
        set_trade_lane("paper")
        strike = strikes[i]
        side = sides[i]
        opt = opts[i]
        symbol = f"NIFTY-{strike}-{opt}"
        case_id = f"ft{i+1:02d}"
        try:
            oid = om.punch_ato(
                symbol=symbol,
                qty=65,
                side=side,
                security_id=f"FT{strike}{opt}",
                reason=f"ft_paper_case_{case_id}",
            )
            results.append({"case": case_id, "symbol": symbol, "side": side, "order_id": oid, "ok": True, "error": None})
            audit("ten_paper_ft.case.ok", mode="paper", case=case_id, symbol=symbol, side=side, order_id=oid)
            log.info("case %s OK %s %s id=%s", case_id, side, symbol, oid)
        except Exception as exc:
            results.append({"case": case_id, "symbol": symbol, "side": side, "order_id": None, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            audit("ten_paper_ft.case.error", mode="paper", case=case_id, symbol=symbol, error=str(exc)[:300])
            log.error("case %s FAIL %s", case_id, exc)

    audit_main, _ = audit_paths(ROOT, "kavach")
    paper_audit = audit_main.parent / "money_audit_paper.jsonl"
    paper_hits = 0
    if paper_audit.is_file():
        for line in paper_audit.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]:
            if "ten_paper_ft" in line and "paper" in line:
                paper_hits += 1

    log_text = ""
    try:
        log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")[-80000:]
    except Exception:
        pass
    log_prefix_ok = PAPER_PREFIX in log_text

    bots = _bots_alive()
    passed = sum(1 for r in results if r["ok"])
    report = {
        "nifty_ref": nifty,
        "strikes": strikes,
        "passed": passed,
        "total": 10,
        "results": results,
        "paper_audit_path": str(paper_audit),
        "paper_audit_hits": paper_hits,
        "log_path": str(log_path),
        "log_has_paper_prefix": log_prefix_ok,
        "trade_lane": get_trade_lane(),
        "bots_alive": bots,
        "all_bots_ok": all(bots.values()),
    }
    out = data_root(ROOT) / "analytics" / "hardening" / f"ten_paper_ft_{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    audit("ten_paper_ft.batch.end", mode="paper", passed=passed, report=str(out))

    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    for r in results:
        print(f"  {r['case']} ok={r['ok']} {r['side']} {r['symbol']} err={r['error']}")

    if passed < 10:
        print("FEEDBACK: paper punches failed — inspect errors above")
        return 2
    if not log_prefix_ok:
        print("FEEDBACK: missing [PAPER TRADE] in bot all.log — check TradeLaneFormatter wiring")
        return 3
    if paper_hits < 1:
        print("FEEDBACK: money_audit_paper.jsonl missing ten_paper_ft events")
        return 5
    if not report["all_bots_ok"]:
        print("FEEDBACK: one or more Phase-1 bots not running:", bots)
        return 4
    print("ALL_TEN_PAPER_FT_GREEN")
    print("REPORT", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
