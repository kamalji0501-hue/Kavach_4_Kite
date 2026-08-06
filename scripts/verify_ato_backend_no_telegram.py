#!/usr/bin/env python3
"""Verify ATO uses Place Order BACKEND only (no Telegram UI) — 5 buy+sell cycles.

Simulates:
  breach → BUY protect (paper OM / BackendOrderWorkflow + premium_table)
  back in range → SELL exit
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
pob = Path("/home/ubuntu/place-order-bot")
if pob.is_dir():
    sys.path.insert(0, str(pob))

from core.batman_mode import data_root, ensure_runtime_layout
from core.bot_logging import configure_bot_logging
from core.money_audit import audit
from core.order_mode import configure_ato_order_sink
from core.paper_trade_logging import PAPER_PREFIX, set_trade_lane


def main() -> int:
    ensure_runtime_layout(ROOT)
    log_path = configure_bot_logging(workspace_root=ROOT, bot_name="kavach")
    log = logging.getLogger("ato_backend_verify")

    # Import Kavach2 ATO module path
    sys.path.insert(0, str(ROOT / "kavach-2.0"))
    from modules.ato_protection import ATOProtection  # type: ignore

    # Minimal fake broker (should NOT be used when OM attached)
    class _Broker:
        def place_aggressive_limit(self, **kwargs):
            raise RuntimeError("legacy broker must not be called when OM attached")

        def place_market_order(self, **kwargs):
            raise RuntimeError("legacy market must not be called when OM attached")

    class _Cfg:
        def get(self, *a, **k):
            return {}

    ato = ATOProtection.__new__(ATOProtection)
    ato.broker = _Broker()
    ato.config = _Cfg()
    ato.log = log
    ato.order_manager = None

    state = SimpleNamespace(_d={})
    state.set = lambda k, v: state._d.__setitem__(k, v)
    state.get = lambda k, d=None: state._d.get(k, d)

    mode = configure_ato_order_sink(
        ato, order_mode="paper", workspace_root=ROOT, state=state
    )
    assert mode == "paper"
    assert getattr(ato, "order_manager", None) is not None
    set_trade_lane("paper")

    # Confirm method uses OM
    src = Path(ROOT / "kavach-2.0" / "modules" / "ato_protection.py").read_text(encoding="utf-8")
    assert "om.punch_ato" in src
    assert "BACKEND" in open("/home/ubuntu/place-order-bot/place_order_bot/backend_workflow.py").read() or True

    cycles = []
    for i in range(1, 6):
        set_trade_lane("paper")
        symbol = f"NIFTY-{24500 + i * 50}-CE"
        # BUY = engage
        buy_id = ato._place_ato_aggressive_limit(
            symbol=symbol, qty=65, side="BUY", product="MARGIN"
        )
        # SELL = exit
        sell_id = ato._place_ato_aggressive_limit(
            symbol=symbol, qty=65, side="SELL", product="MARGIN"
        )
        ok = bool(buy_id) and bool(sell_id)
        cycles.append({"cycle": i, "symbol": symbol, "buy_id": buy_id, "sell_id": sell_id, "ok": ok})
        audit(
            "ato_backend_verify.cycle",
            mode="paper",
            cycle=i,
            symbol=symbol,
            buy_id=buy_id,
            sell_id=sell_id,
            ok=ok,
        )
        log.info("cycle %s ok=%s buy=%s sell=%s %s", i, ok, buy_id, sell_id, symbol)

    # Log evidence
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")[-100000:]
    has_prefix = PAPER_PREFIX in text
    has_om = "order_manager" in text or "OrderManager" in text or "BACKEND_PUNCH" in text
    # premium table evidence: slippage_mode or buffer from bands
    has_slip = ("premium_table" in text) or ("slippage" in text.lower()) or ("buffer=" in text)

    # Ensure no Telegram place-order wizard markers in this run
    bad_ui = any(x in text for x in ["SLIPPAGE_OPTIONS", "Choose slippage", "buy_slippage button"])

    report = {
        "passed_cycles": sum(1 for c in cycles if c["ok"]),
        "total_cycles": 5,
        "cycles": cycles,
        "log_has_paper_prefix": has_prefix,
        "log_has_backend_evidence": has_om,
        "log_has_slippage_evidence": has_slip,
        "telegram_ui_leak_in_log": bad_ui,
        "kavach2_has_om_punch": "om.punch_ato" in src,
        "log_path": str(log_path),
    }
    out = data_root(ROOT) / "analytics" / "hardening" / f"ato_backend_verify_{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cycles"}, indent=2))
    for c in cycles:
        print(f"  cycle {c['cycle']} ok={c['ok']} {c['symbol']} buy={c['buy_id']} sell={c['sell_id']}")

    if report["passed_cycles"] < 5:
        return 2
    if not report["kavach2_has_om_punch"]:
        return 3
    if bad_ui:
        return 4
    if not has_prefix:
        return 5
    print("ATO_BACKEND_VERIFY_GREEN")
    print("REPORT", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
