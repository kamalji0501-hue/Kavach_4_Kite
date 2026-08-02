"""
Batman v3 — Overnight Hedge Module.

Before the configured cutoff time (default 15:15 IST) on
NON-expiry days, buys 1-lot OTM CE + PE at ``hedge_distance``
points from spot as overnight protection against gap moves.

Hedges are automatically closed the next morning if the module
is still running, or they can be closed via Telegram.
"""

from __future__ import annotations

import logging

from core import utils
from core.event_bus import Event
from core.module_base import ModuleBase

logger = logging.getLogger(__name__)


class OvernightHedge(ModuleBase):
    name = "overnight_hedge"

    def _run(self) -> None:
        cfg = self.config.get("hedge", {})
        distance = cfg.get("distance_from_spot", 500)
        hedge_lots = cfg.get("lots", 1)
        cutoff_time = cfg.get("cutoff_time", "15:15")

        strat = self.config.get("strategy", {})
        lot_size = strat.get("lot_size", 75)
        product = strat.get("product_type", "MARGIN")
        index = strat.get("index", "NIFTY")
        expiry_weekday = _day_name_to_int(strat.get("expiry_day", "Tuesday"))

        self.log.info(
            "Overnight Hedge active — %dpts from spot, cutoff %s",
            distance,
            cutoff_time,
        )

        while not self._stop_event.is_set():
            try:
                # Skip expiry day — no overnight hold
                if utils.is_expiry_day(expiry_weekday):
                    if self._sleep(60):
                        return
                    continue

                if not utils.is_market_hours():
                    if self._sleep(30):
                        return
                    continue

                # Only place hedge once
                if self.state.get("hedge.active", False):
                    if self._sleep(60):
                        return
                    continue

                # Wait until cutoff window
                now = utils.now_ist()
                from datetime import time

                cutoff = time.fromisoformat(cutoff_time)
                if now.time() < cutoff:
                    if self._sleep(30):
                        return
                    continue

                # Place hedge!
                self._place_hedge(index, distance, hedge_lots, lot_size, product)

            except Exception as exc:
                self.log.error("Hedge error: %s", exc)

            if self._sleep(30):
                return

    def _place_hedge(
        self,
        index: str,
        distance: int,
        hedge_lots: int,
        lot_size: int,
        product: str,
    ) -> None:
        """Buy OTM CE + PE as overnight hedge."""
        step = utils.NIFTY_STRIKE_STEP
        otm_steps = utils.otm_count_from_distance(distance, step)
        qty = hedge_lots * lot_size

        self.log.info("═══ PLACING OVERNIGHT HEDGE ═══")

        ce_sym, pe_sym, ce_strike, pe_strike = self.broker.otm_strike(
            underlying=index, expiry=0, otm_count=otm_steps
        )

        try:
            ce_oid = self.broker.place_market_order(
                symbol=ce_sym, qty=qty, side="BUY", trade_type=product
            )
            pe_oid = self.broker.place_market_order(
                symbol=pe_sym, qty=qty, side="BUY", trade_type=product
            )

            self.state.set("hedge.active", True, save=False)
            self.state.set("hedge.ce_symbol", ce_sym, save=False)
            self.state.set("hedge.pe_symbol", pe_sym, save=False)
            self.state.set("hedge.ce_order_id", ce_oid, save=False)
            self.state.set("hedge.pe_order_id", pe_oid)

            self.log.info("✅ Hedge placed — BUY %d × %s + %s", qty, ce_sym, pe_sym)
            self.events.publish(
                Event.HEDGE_PLACED,
                {
                    "ce_symbol": ce_sym,
                    "pe_symbol": pe_sym,
                    "ce_strike": ce_strike,
                    "pe_strike": pe_strike,
                    "qty": qty,
                },
            )

        except Exception as exc:
            self.log.error("❌ Hedge placement FAILED: %s", exc)

    def close_hedge(self) -> None:
        """Close outstanding hedge positions (callable from Telegram)."""
        ce_sym = self.state.get("hedge.ce_symbol")
        pe_sym = self.state.get("hedge.pe_symbol")
        product = self.config.get("strategy.product_type", "MARGIN")
        lot_size = self.config.get("strategy.lot_size", 75)
        hedge_lots = self.config.get("hedge.lots", 1)
        qty = hedge_lots * lot_size

        closed = []
        for sym in [ce_sym, pe_sym]:
            if sym:
                try:
                    self.broker.close_position(symbol=sym, qty=qty, side="SELL", trade_type=product)
                    closed.append(sym)
                except Exception as exc:
                    self.log.error("Failed to close hedge %s: %s", sym, exc)

        if closed:
            self.state.set("hedge.active", False, save=False)
            self.state.set("hedge.ce_symbol", None, save=False)
            self.state.set("hedge.pe_symbol", None, save=False)
            self.state.set("hedge.ce_order_id", None, save=False)
            self.state.set("hedge.pe_order_id", None)
            self.log.info("Hedge closed: %s", closed)
            self.events.publish(Event.HEDGE_CLOSED, {"symbols": closed})


def _day_name_to_int(name: str) -> int:
    days = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    return days.get(name.strip().lower(), 1)
