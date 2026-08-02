"""
Batman v3 — Emergency Exit Module.

Listens for ``EMERGENCY_EXIT`` events (from trailing stop,
Telegram /exit command, etc.) and immediately closes all
open positions.

Also runs a simple watchdog: if the module detects catastrophic
P&L (beyond ``emergency_threshold``), it triggers an exit on
its own.
"""

from __future__ import annotations

import logging
from typing import Any

from core import utils
from core.event_bus import Event
from core.module_base import ModuleBase

logger = logging.getLogger(__name__)


class EmergencyExit(ModuleBase):
    name = "emergency_exit"

    def _run(self) -> None:
        # Subscribe to emergency events from other modules
        self.events.subscribe(Event.EMERGENCY_EXIT, self._handle_emergency)

        emergency_threshold = self.config.get("trailing.hard_stop_loss", -8000)
        check_interval = self.config.get("trailing.check_interval_seconds", 10)

        self.log.info("Emergency Exit watchdog active — threshold ₹%s", emergency_threshold)

        while not self._stop_event.is_set():
            try:
                if utils.is_market_hours():
                    pnl = self.broker.get_live_pnl()
                    if pnl <= emergency_threshold:
                        self.log.critical(
                            "🚨 EMERGENCY — PnL ₹%.0f breached threshold ₹%.0f",
                            pnl,
                            emergency_threshold,
                        )
                        self.execute_exit("emergency_watchdog")
                        return
            except Exception as exc:
                self.log.error("Watchdog error: %s", exc)

            if self._sleep(check_interval):
                return

    def _handle_emergency(self, event: Event, data: dict[str, Any]) -> None:
        """Callback when an EMERGENCY_EXIT event is received."""
        reason = data.get("reason", "unknown")
        source = data.get("source", "unknown")
        self.log.warning("Emergency event received from %s — reason: %s", source, reason)
        self.execute_exit(reason)

    def execute_exit(self, reason: str = "manual") -> dict[str, Any]:
        """Close ALL positions immediately.  Returns a summary dict."""
        self.log.critical("═══ EMERGENCY EXIT — %s ═══", reason.upper())

        product = self.config.get("strategy.product_type", "MARGIN")

        try:
            order_ids = self.broker.close_all_positions(trade_type=product)
            result = {
                "success": True,
                "reason": reason,
                "orders_placed": len(order_ids),
                "order_ids": order_ids,
                "timestamp": utils.now_ist().isoformat(),
            }
            self.log.info("Exit complete — %d orders placed", len(order_ids))
            self.events.publish(Event.ALL_POSITIONS_CLOSED, result)

            # Reset state — also lock the entry gate so BatmanEntry
            # cannot redeploy into a session that already had an emergency exit.
            self.state.set("positions.ce_sell", None, save=False)
            self.state.set("positions.ce_buy", None, save=False)
            self.state.set("positions.pe_sell", None, save=False)
            self.state.set("positions.pe_buy", None, save=False)
            self.state.set("trailing.active", False, save=False)
            self.state.set("hedge.active", False, save=False)
            # Reset ATO state — physical ATO legs are closed by close_all_positions above;
            # resetting flags here prevents the ATO module from treating orphaned state
            # as an active position and re-firing retrace logic after exit.
            self.state.set("ato.ce_triggered", False, save=False)
            self.state.set("ato.pe_triggered", False, save=False)
            self.state.set("ato.ce_ato_active", False, save=False)
            self.state.set("ato.pe_ato_active", False, save=False)
            self.state.set("ato.ce_order_id", None, save=False)
            self.state.set("ato.pe_order_id", None, save=False)
            self.state.set("session.emergency_exited", True)

            return result

        except Exception as exc:
            self.log.error("❌ Emergency exit FAILED: %s", exc)
            return {
                "success": False,
                "reason": reason,
                "error": str(exc),
                "timestamp": utils.now_ist().isoformat(),
            }

    def _on_stop(self) -> None:
        self.events.unsubscribe(Event.EMERGENCY_EXIT, self._handle_emergency)
