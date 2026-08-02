"""
Batman v3 — Profit Trailing Module (Expiry Day).

Runs on expiry day (Tuesday by default).  Tracks live M2M P&L and:

    • Hard stop:  If M2M ≤ hard_stop_loss (−₹8000) → exit all.
    • Activation: If M2M ≥ activation_profit (+₹12000) → start trailing.
    • Trailing:   While trailing, track peak_profit.  If M2M drops by
                  trailing_distance (₹2000) from peak → exit all.

Peak ratchets UP only — never down.
"""

from __future__ import annotations

import logging

from core import utils
from core.event_bus import Event
from core.module_base import ModuleBase

logger = logging.getLogger(__name__)


class ProfitTrailing(ModuleBase):
    name = "profit_trailing"

    def _run(self) -> None:
        cfg = self.config.get("trailing", {})
        hard_stop = cfg.get("hard_stop_loss", -8000)
        activation = cfg.get("activation_profit", 12000)
        trail_dist = cfg.get("trailing_distance", 2000)
        interval = cfg.get("check_interval_seconds", 5)

        strat = self.config.get("strategy", {})
        expiry_day_name = strat.get("expiry_day", "Tuesday")
        expiry_weekday = _day_name_to_int(expiry_day_name)

        self.log.info(
            "Profit Trailing active — hard_stop=%s, activation=%s, trail=%s",
            hard_stop,
            activation,
            trail_dist,
        )

        while not self._stop_event.is_set():
            try:
                # Only trail on expiry day during market hours
                if not utils.is_expiry_day(expiry_weekday):
                    if self._sleep(60):
                        return
                    continue

                if not utils.is_market_hours():
                    if self._sleep(30):
                        return
                    continue

                pnl = self.broker.get_live_pnl()
                trailing_active = self.state.get("trailing.active", False)
                peak = self.state.get("trailing.peak_profit", 0)

                # ── Hard stop ────────────────────────────────
                if pnl <= hard_stop:
                    self.log.critical("🔴 HARD STOP HIT — PnL ₹%.0f ≤ ₹%.0f", pnl, hard_stop)
                    self._exit_all("hard_stop")
                    self.state.set("trailing.hard_stop_hit", True)
                    self.events.publish(Event.HARD_STOP_HIT, {"pnl": pnl})
                    return  # module done

                # ── Check activation ─────────────────────────
                if not trailing_active and pnl >= activation:
                    self.log.info(
                        "🟢 TRAILING ACTIVATED — PnL ₹%.0f ≥ ₹%.0f",
                        pnl,
                        activation,
                    )
                    self.state.set("trailing.active", True, save=False)
                    self.state.set("trailing.peak_profit", pnl, save=False)
                    self.state.set("trailing.trailing_stop", pnl - trail_dist)
                    trailing_active = True
                    peak = pnl

                    self.events.publish(Event.TRAILING_ACTIVATED, {"pnl": pnl})

                # ── Trail the stop ───────────────────────────
                if trailing_active:
                    if pnl > peak:
                        peak = pnl
                        new_stop = peak - trail_dist
                        self.state.set("trailing.peak_profit", peak, save=False)
                        self.state.set("trailing.trailing_stop", new_stop)
                        self.log.info(
                            "📈 New peak ₹%.0f — trailing stop ₹%.0f",
                            peak,
                            new_stop,
                        )

                    trailing_stop = self.state.get("trailing.trailing_stop", 0)
                    if pnl <= trailing_stop:
                        self.log.warning(
                            "⚠ TRAILING STOP HIT — PnL ₹%.0f ≤ stop ₹%.0f",
                            pnl,
                            trailing_stop,
                        )
                        self._exit_all("trailing_stop")
                        self.events.publish(
                            Event.TRAILING_STOP_HIT,
                            {"pnl": pnl, "peak": peak, "stop": trailing_stop},
                        )
                        return  # module done

            except Exception as exc:
                self.log.error("Trailing check error: %s", exc)

            if self._sleep(interval):
                return

    def _exit_all(self, reason: str) -> None:
        """Route all-position close through the EmergencyExit module via event.

        Publishes EMERGENCY_EXIT only — the EmergencyExit module's subscriber
        handles the actual broker call, state reset, and ALL_POSITIONS_CLOSED
        event.  Do NOT call broker.close_all_positions() here: that would
        create a double-close (positions already being closed by EmergencyExit)
        and would fire ALL_POSITIONS_CLOSED and Telegram alerts twice.
        """
        self.log.warning("EXIT ALL via emergency event — reason: %s", reason)
        self.events.publish(Event.EMERGENCY_EXIT, {"reason": reason, "source": self.name})


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
