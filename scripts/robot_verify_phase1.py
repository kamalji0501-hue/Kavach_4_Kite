#!/usr/bin/env python3
"""Robot verify Phase-1: compile, pytest, paper/live, CSV, audit.

Run on VPS:
  cd /home/ubuntu/rahul_Changes
  .venv/bin/python scripts/robot_verify_phase1.py
"""
from __future__ import annotations

import os
import py_compile
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
POB = Path("/home/ubuntu/place-order-bot")
sys.path.insert(0, str(ROOT))
if POB.is_dir():
    sys.path.insert(0, str(POB))

FAILURES: list[str] = []
IST = ZoneInfo("Asia/Kolkata")


def ok(m: str) -> None:
    print(f"  PASS  {m}")


def bad(m: str) -> None:
    print(f"  FAIL  {m}")
    FAILURES.append(m)


def section(t: str) -> None:
    print(f"\n=== {t} ===")


def compile_critical() -> None:
    section("compile")
    for rel in [
        "core/order_mode.py",
        "core/paper_position_book.py",
        "core/ato_nifty_tick_csv.py",
        "core/money_audit.py",
        "core/order_manager.py",
        "modules/ato_protection.py",
        "kavach-2.0/bat_telegram/bots/kavach2/register_wizard.py",
        "kavach-2.0/bat_telegram/bots/kavach2/bot.py",
        "run_kavach2.py",
    ]:
        try:
            py_compile.compile(str(ROOT / rel), doraise=True)
            ok(rel)
        except Exception as e:
            bad(f"{rel}: {e}")


def pytest_suites() -> None:
    section("pytest")
    suites = [
        "tests/test_order_mode_register.py",
        "tests/test_wizard_plan.py",
        "tests/test_money_audit.py",
        "tests/test_ato_nifty_tick_csv.py",
        "tests/test_robot_phase1_integration.py",
    ]
    cmd = [str(ROOT / ".venv/bin/pytest"), *[s for s in suites if (ROOT / s).exists()], "-q", "--tb=line"]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}:{POB}" if POB.is_dir() else str(ROOT)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
    print((r.stdout or "")[-1500:])
    if r.returncode != 0:
        print((r.stderr or "")[-1500:])
        bad(f"pytest rc={r.returncode}")
    else:
        ok("pytest suites")


def smoke() -> None:
    section("smoke paper/live/csv/audit")
    from core.money_audit import redact
    from core.order_mode import configure_ato_order_sink
    from core.wizard_plan import build_wizard_plan
    from modules.ato_protection import ATOProtection
    import core.ato_nifty_tick_csv as csvm
    from core.ato_nifty_tick_csv import (
        get_ato_tick_csv_writer,
        record_nifty_tick,
        record_option_quotes,
        record_registration,
    )
    from bat_telegram.bots.kavach2.register_wizard import WIZARD_ORDER_MODE, build_wizard_handler

    if redact({"token": "X", "qty": 1})["token"] != "<redacted>":
        bad("redact")
    else:
        ok("redact")

    class Boom:
        def place_aggressive_limit(self, **k):
            raise AssertionError("broker")

        def place_market_order(self, **k):
            raise AssertionError("broker")

    class Ato:
        order_manager = None
        broker = Boom()
        log = __import__("logging").getLogger("robot_verify")

        def _operator_settings(self):
            return {}

    ato = Ato()
    configure_ato_order_sink(ato, order_mode="paper", workspace_root=ROOT)
    if ato.order_manager is None:
        bad("paper OM")
    else:
        ok("paper OM")
        td = Path(tempfile.mkdtemp())
        ato.order_manager.ledger_dir = td
        ato.order_manager._paper_wf = None
        ato.order_manager.default_ltp = 100.0
        try:
            oid = ATOProtection._place_ato_aggressive_limit(
                ato, symbol="NIFTY V", qty=65, side="BUY", product="MARGIN"
            )
            ok(f"paper punch {oid}")
        except AssertionError:
            bad("paper hit broker")
        except Exception as e:
            bad(f"paper punch: {e}")

    configure_ato_order_sink(ato, order_mode="live", workspace_root=ROOT)
    if ato.order_manager is not None:
        bad("live OM not cleared")
    else:
        ok("live OM cleared")
    try:
        ATOProtection._place_ato_aggressive_limit(
            ato, symbol="NIFTY V", qty=65, side="BUY", product="MARGIN"
        )
        bad("live should call broker")
    except AssertionError:
        ok("live broker path")

    csvm._WRITER = None
    w = get_ato_tick_csv_writer(ROOT)
    path = record_registration(
        ce_symbol="CE", ce_strike=25000, ce_mode="AUTO",
        pe_symbol="PE", pe_strike=24500, pe_mode="CUSTOM", nifty_ltp=24700,
    )
    now = datetime.now(IST)
    record_nifty_tick(now, 24701.0, source="nifty_ws")
    record_option_quotes(now, {"ce_protect": 10.0, "pe_protect": 20.0})
    w.flush()
    if path and path.exists() and "CUSTOM" in path.read_text(encoding="utf-8"):
        ok(f"csv {path.name}")
    else:
        bad("csv")

    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    if plan[0] != "order_mode":
        bad("plan")
    else:
        ok("plan order_mode first")

    h = build_wizard_handler(60)
    if WIZARD_ORDER_MODE not in h.states:
        bad("handler")
    else:
        ok("handler ORDER_MODE")

    if POB.is_dir():
        from place_order_bot.backend_workflow import BackendOrderWorkflow, PunchRequest

        wf = BackendOrderWorkflow.for_paper(
            ledger_path=Path("/tmp/robot_verify_paper.sqlite3"), ltp=100
        )
        res = wf.punch(
            PunchRequest(side="BUY", quantity=65, security_id="1", trading_symbol="X")
        )
        if int(res.filled_qty) == 65:
            ok("backend 65 fill")
        else:
            bad(f"backend filled={res.filled_qty}")


def main() -> int:
    print("ROBOT VERIFY Phase-1")
    print("ROOT", ROOT)
    compile_critical()
    pytest_suites()
    smoke()
    section("SUMMARY")
    if FAILURES:
        print(f"FAILED {len(FAILURES)}")
        for f in FAILURES:
            print(" -", f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
