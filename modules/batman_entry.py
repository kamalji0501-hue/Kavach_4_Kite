"""
Batman v3 — Iron Condor Entry Module.

Deploys a 4-leg NIFTY weekly iron condor on entry-day (Wednesday)
at the configured entry time (11:00 AM by default).

Sizing rule (1 Batman lot = N buy_lots):

    CE Sell  → 2 × buy_lots × lot_size  (SELL, 2:1 ratio)
    CE Buy   → 1 × buy_lots × lot_size  (BUY hedge)
    PE Sell  → 2 × buy_lots × lot_size  (SELL, 2:1 ratio)
    PE Buy   → 1 × buy_lots × lot_size  (BUY hedge)

User sets only ``strategy.buy_lots`` in settings.json.
``sell_lots`` is always auto-computed as ``buy_lots * 2``.

All strikes are resolved via Tradehull's ``OTM_Strike_Selection``.
"""

from __future__ import annotations

import logging
from typing import Any

from core import utils
from core.event_bus import Event
from core.module_base import ModuleBase

logger = logging.getLogger(__name__)


class BatmanEntry(ModuleBase):
    name = "batman_entry"

    def _run(self) -> None:
        self.log.info("Batman Entry module running — waiting for entry conditions")

        while not self._stop_event.is_set():
            try:
                if not self._should_deploy():
                    if self._sleep(30):
                        return
                    continue

                self._deploy_iron_condor()

                # After deployment, stay alive but idle until stopped
                self.log.info("Deployment done — module will idle")
                while not self._stop_event.is_set():
                    if self._sleep(60):
                        return

            except Exception as exc:
                self.log.error("Entry error: %s", exc)
                if self._sleep(30):
                    return

    def _should_deploy(self) -> bool:
        """True if today is entry day, it's past entry time, and
        no positions are deployed yet."""
        strat = self.config.get("strategy", {})
        entry_day_name = strat.get("entry_day", "Wednesday")
        entry_time = strat.get("entry_time", "11:00")

        entry_weekday = _day_name_to_int(entry_day_name)

        if not utils.is_entry_window(entry_weekday):
            return False
        if not utils.is_market_hours():
            return False

        now = utils.now_ist()
        from datetime import time

        target = time.fromisoformat(entry_time)
        if now.time() < target:
            return False

        # Already deployed?
        if self.state.get("positions.ce_sell") is not None:
            return False

        # Block re-entry after an emergency exit in the same session.
        # Operator must explicitly reset state (via /reset or restart) before
        # a new deployment is allowed.
        if self.state.get("session.emergency_exited", False):
            self.log.warning(
                "Re-entry blocked — emergency exit occurred this session. "
                "Reset state to allow a new deployment."
            )
            return False

        return True

    def _deploy_iron_condor(self) -> None:
        """Place all 4 legs of the iron condor."""
        strat = self.config.get("strategy", {})
        sell_distance = strat.get("sell_distance", 300)
        hedge_gap = strat.get("hedge_gap", 250)
        buy_lots = strat.get("buy_lots", 1)
        sell_lots = buy_lots * 2  # always 2× buy — 1:2 Batman ratio
        lot_size = strat.get("lot_size", 65)
        product = strat.get("product_type", "MARGIN")
        index = strat.get("index", "NIFTY")

        self.log.info("═══ DEPLOYING IRON CONDOR ═══")
        self.events.publish(Event.ENTRY_STARTED, {"index": index})

        spot = self.broker.get_nifty_ltp()
        self.log.info("Spot: %.1f", spot)

        strikes = utils.calculate_strikes(spot, sell_distance, hedge_gap)
        self.log.info("Strikes: %s", strikes)

        sell_otm = strikes["sell_otm"]
        buy_otm = strikes["buy_otm"]

        # Resolve symbols via Tradehull
        ce_sell_sym, pe_sell_sym, ce_sell_strike, pe_sell_strike = self.broker.otm_strike(
            underlying=index, expiry=0, otm_count=sell_otm
        )
        ce_buy_sym, pe_buy_sym, ce_buy_strike, pe_buy_strike = self.broker.otm_strike(
            underlying=index, expiry=0, otm_count=buy_otm
        )

        # ATO protection symbols — one strike beyond sell (sell_otm + 1 = +50 pts)
        # Stored in state so ato_protection.py can use them on breach without
        # recalculating from a shifted ATM.
        ce_ato_sym, pe_ato_sym, ce_ato_strike, pe_ato_strike = self.broker.otm_strike(
            underlying=index, expiry=0, otm_count=sell_otm + 1
        )
        self.log.info(
            "ATO protect symbols → CE %d (%s) | PE %d (%s)",
            ce_ato_strike,
            ce_ato_sym,
            pe_ato_strike,
            pe_ato_sym,
        )

        sell_qty = sell_lots * lot_size
        buy_qty = buy_lots * lot_size

        legs_info: dict[str, Any] = {}

        try:
            # ── Leg 1: CE SELL ───────────────────────────────
            self.log.info("Leg 1 → SELL %d × %s", sell_qty, ce_sell_sym)
            oid_ce_sell = self.broker.place_market_order(
                symbol=ce_sell_sym, qty=sell_qty, side="SELL", trade_type=product
            )
            legs_info["ce_sell"] = {
                "symbol": ce_sell_sym,
                "strike": ce_sell_strike,
                "qty": -sell_qty,
                "order_id": oid_ce_sell,
            }

            # ── Leg 2: CE BUY (hedge) ───────────────────────
            self.log.info("Leg 2 → BUY  %d × %s", buy_qty, ce_buy_sym)
            oid_ce_buy = self.broker.place_market_order(
                symbol=ce_buy_sym, qty=buy_qty, side="BUY", trade_type=product
            )
            legs_info["ce_buy"] = {
                "symbol": ce_buy_sym,
                "strike": ce_buy_strike,
                "qty": buy_qty,
                "order_id": oid_ce_buy,
            }

            # ── Leg 3: PE SELL ───────────────────────────────
            self.log.info("Leg 3 → SELL %d × %s", sell_qty, pe_sell_sym)
            oid_pe_sell = self.broker.place_market_order(
                symbol=pe_sell_sym, qty=sell_qty, side="SELL", trade_type=product
            )
            legs_info["pe_sell"] = {
                "symbol": pe_sell_sym,
                "strike": pe_sell_strike,
                "qty": -sell_qty,
                "order_id": oid_pe_sell,
            }

            # ── Leg 4: PE BUY (hedge) ───────────────────────
            self.log.info("Leg 4 → BUY  %d × %s", buy_qty, pe_buy_sym)
            oid_pe_buy = self.broker.place_market_order(
                symbol=pe_buy_sym, qty=buy_qty, side="BUY", trade_type=product
            )
            legs_info["pe_buy"] = {
                "symbol": pe_buy_sym,
                "strike": pe_buy_strike,
                "qty": buy_qty,
                "order_id": oid_pe_buy,
            }

            # Persist to state
            for leg_key, leg_data in legs_info.items():
                self.state.set(f"positions.{leg_key}", leg_data, save=False)

            # Store ATO protection symbols for ato_protection module
            self.state.set("ato.ce_protect_symbol", ce_ato_sym, save=False)
            self.state.set("ato.ce_protect_strike", ce_ato_strike, save=False)
            self.state.set("ato.pe_protect_symbol", pe_ato_sym, save=False)
            self.state.set("ato.pe_protect_strike", pe_ato_strike, save=False)
            self.state.save()

            self.log.info("═══ IRON CONDOR DEPLOYED ═══")
            self.events.publish(
                Event.ENTRY_COMPLETED,
                {
                    "spot": spot,
                    "legs": legs_info,
                },
            )

        except Exception as exc:
            self.log.error("❌ Iron condor deployment FAILED: %s", exc)
            self.events.publish(
                Event.ENTRY_FAILED,
                {
                    "error": str(exc),
                    "partial_legs": legs_info,
                },
            )
            raise


def _day_name_to_int(name: str) -> int:
    """'Monday' → 0, 'Tuesday' → 1, … 'Sunday' → 6."""
    days = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    return days.get(name.strip().lower(), 2)
