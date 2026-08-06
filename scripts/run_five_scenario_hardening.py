#!/usr/bin/env python3
"""Five-scenario hardening loop for rahul_Changes (no trading-logic changes).

Runs scenarios repeatedly, validates money_audit + artifacts, writes a report.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
POB = Path("/home/ubuntu/place-order-bot")
sys.path.insert(0, str(ROOT))
if POB.is_dir():
    sys.path.insert(0, str(POB))

IST = ZoneInfo("Asia/Kolkata")
REPORT_DIR = ROOT / "data" / "analytics" / "hardening"
# Prefer runtime data if available
try:
    from core.batman_mode import data_root
    REPORT_DIR = data_root(ROOT) / "analytics" / "hardening"
except Exception:
    pass


def _audit_path() -> Path | None:
    try:
        from core.money_audit import audit_paths
        return audit_paths(ROOT, "kavach")[0]
    except Exception:
        return None


def _read_audit_events(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    ev = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]:
        try:
            ev.add(json.loads(line).get("event") or "")
        except Exception:
            pass
    return ev


def scenario_1_robot_verify() -> tuple[bool, str]:
    r = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/robot_verify_phase1.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": f"{ROOT}:{POB}"},
    )
    ok = r.returncode == 0 and "ALL CHECKS PASSED" in (r.stdout or "")
    return ok, (r.stdout or "")[-800:]


def scenario_2_paper_punch_x3() -> tuple[bool, str]:
    from core.order_mode import configure_ato_order_sink
    from core.money_audit import configure_money_audit, audit
    from modules.ato_protection import ATOProtection
    from core.bot_logging import configure_bot_logging

    configure_bot_logging(workspace_root=ROOT, bot_name="kavach")
    audit("scenario.paper_punch.start")

    class Boom:
        def place_aggressive_limit(self, **k):
            raise AssertionError("broker")
        def place_market_order(self, **k):
            raise AssertionError("broker")

    class Ato:
        order_manager = None
        broker = Boom()
        log = __import__("logging").getLogger("s2")
        def _operator_settings(self):
            return {}

    ato = Ato()
    configure_ato_order_sink(ato, order_mode="paper", workspace_root=ROOT)
    td = Path(tempfile.mkdtemp())
    ato.order_manager.ledger_dir = td
    ato.order_manager._paper_wf = None
    ato.order_manager.default_ltp = 100.0
    ids = []
    for i in range(3):
        oid = ATOProtection._place_ato_aggressive_limit(
            ato, symbol=f"NIFTY S2-{i}", qty=65, side="BUY", product="MARGIN"
        )
        ids.append(oid)
    audit("scenario.paper_punch.done", count=3, ids=ids)
    ev = _read_audit_events(_audit_path())
    need = {"ato.order_sink.decision", "order_manager.punch_ato.ok", "backend.punch.done"}
    missing = need - ev
    return (not missing), f"ids={ids} missing={missing}"


def scenario_3_live_sink() -> tuple[bool, str]:
    from core.order_mode import configure_ato_order_sink
    from core.money_audit import audit
    from modules.ato_protection import ATOProtection

    class Boom:
        def place_aggressive_limit(self, **k):
            raise AssertionError("broker-hit")
        def place_market_order(self, **k):
            raise AssertionError("broker-hit")

    class Ato:
        order_manager = object()
        broker = Boom()
        log = __import__("logging").getLogger("s3")
        def _operator_settings(self):
            return {}

    ato = Ato()
    configure_ato_order_sink(ato, order_mode="live", workspace_root=ROOT)
    audit("scenario.live_sink.cleared", om=str(ato.order_manager))
    if ato.order_manager is not None:
        return False, "OM not cleared"
    try:
        ATOProtection._place_ato_aggressive_limit(
            ato, symbol="NIFTY L", qty=65, side="BUY", product="MARGIN"
        )
        return False, "broker not called"
    except AssertionError as e:
        return ("broker" in str(e)), str(e)


def scenario_4_tick_csv() -> tuple[bool, str]:
    from datetime import datetime
    import core.ato_nifty_tick_csv as m
    from core.ato_nifty_tick_csv import (
        get_ato_tick_csv_writer, record_registration, record_nifty_tick, record_option_quotes,
    )
    from core.money_audit import audit

    m._WRITER = None
    w = get_ato_tick_csv_writer(ROOT)
    path = record_registration(
        ce_symbol="CE-S4", ce_strike=25000, ce_mode="AUTO",
        pe_symbol="PE-S4", pe_strike=24500, pe_mode="CUSTOM", nifty_ltp=24700.0,
    )
    now = datetime.now(IST)
    for i in range(5):
        record_nifty_tick(now, 24700.0 + i, source="nifty_ws")
    record_option_quotes(now, {"ce_protect": 11.0, "pe_protect": 22.0})
    w.flush()
    text = path.read_text(encoding="utf-8") if path else ""
    ok = path is not None and path.exists() and "CE-S4" in text and "22.00" in text
    audit("scenario.tick_csv.done", path=str(path), ok=ok, bytes=len(text))
    return ok, f"path={path} bytes={len(text)}"


def scenario_5_wizard_and_settings() -> tuple[bool, str]:
    import json
    from core.wizard_plan import build_wizard_plan, question_index
    from bat_telegram.bots.kavach.register_wizard import WIZARD_ORDER_MODE, _CB_ORDER_MODE, build_wizard_handler
    from core.money_audit import audit

    plan = build_wizard_plan(pe_enabled=True, ce_enabled=True)
    idx, total = question_index(plan, "order_mode")
    h = build_wizard_handler(30)
    settings = json.loads((ROOT / "config/settings.json").read_text(encoding="utf-8"))["logging"]
    ok = (
        plan[0] == "order_mode"
        and idx == 1
        and WIZARD_ORDER_MODE in h.states
        and _CB_ORDER_MODE == "wiz_omode"
        and settings.get("level") == "DEBUG"
        and settings.get("audit_jsonl") is True
    )
    audit("scenario.wizard_settings.done", ok=ok, total=total, level=settings.get("level"))
    return ok, f"plan0={plan[0]} total={total} level={settings.get('level')}"


SCENARIOS = [
    ("S1_robot_verify", scenario_1_robot_verify),
    ("S2_paper_punch_x3", scenario_2_paper_punch_x3),
    ("S3_live_sink", scenario_3_live_sink),
    ("S4_tick_csv", scenario_4_tick_csv),
    ("S5_wizard_settings", scenario_5_wizard_and_settings),
]


def main() -> int:
    cycles = int(os.environ.get("HARDEN_CYCLES", "5"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    results = []
    print(f"FIVE-SCENARIO HARDENING cycles={cycles} root={ROOT}")
    all_green = True
    for c in range(1, cycles + 1):
        print(f"\n######## CYCLE {c}/{cycles} ########")
        cycle = {"cycle": c, "scenarios": []}
        for name, fn in SCENARIOS:
            t0 = time.time()
            try:
                ok, detail = fn()
            except Exception as e:
                ok, detail = False, f"EXC {type(e).__name__}: {e}"
            dt = round(time.time() - t0, 3)
            print(f"  {'PASS' if ok else 'FAIL'}  {name} ({dt}s)  {detail[:160]}")
            cycle["scenarios"].append({"name": name, "ok": ok, "detail": detail[:500], "seconds": dt})
            if not ok:
                all_green = False
        results.append(cycle)

    report = {
        "ts": datetime.now(IST).isoformat(),
        "cycles": cycles,
        "all_green": all_green,
        "results": results,
        "audit_path": str(_audit_path()),
    }
    out = REPORT_DIR / f"five_scenario_{stamp}.json"
    latest = REPORT_DIR / "LATEST_FIVE_SCENARIO.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = REPORT_DIR / "LATEST_FIVE_SCENARIO.md"
    lines = [f"# Five-scenario hardening", f"", f"all_green: **{all_green}**", f"cycles: {cycles}", f"audit: `{report['audit_path']}`", ""]
    for c in results:
        lines.append(f"## Cycle {c['cycle']}")
        for s in c["scenarios"]:
            lines.append(f"- {'PASS' if s['ok'] else 'FAIL'} `{s['name']}` ({s['seconds']}s)")
        lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {md}")
    print("ALL_GREEN" if all_green else "HAD_FAILURES")
    return 0 if all_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
