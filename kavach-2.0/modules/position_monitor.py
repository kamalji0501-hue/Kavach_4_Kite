"""
Batman v3 — Position Monitor Module.

Periodically reports MTM P&L and position status.
Sends Telegram alerts when negative MTM exceeds a threshold.
Publishes ``MTM_UPDATE`` and ``MTM_ALERT`` events.
"""

from __future__ import annotations

import logging
from typing import Any

from core import utils
from core.event_bus import Event
from core.module_base import ModuleBase

logger = logging.getLogger(__name__)


class PositionMonitor(ModuleBase):
    name = "position_monitor"

    def _run(self) -> None:
        cfg = self.config.get("monitor", {})
        report_interval = cfg.get("report_interval_seconds", 300)
        alert_threshold = cfg.get("mtm_alert_threshold", -5000)
        alert_on_negative = cfg.get("alert_on_negative", True)

        self.log.info(
            "Position Monitor active — report every %ds, alert threshold ₹%s",
            report_interval,
            alert_threshold,
        )

        _last_alert_pnl = None

        while not self._stop_event.is_set():
            try:
                if not utils.is_market_hours():
                    if self._sleep(60):
                        return
                    continue

                pnl = self.broker.get_live_pnl()
                positions_df = self.broker.get_positions()

                position_count = 0
                if positions_df is not None and not positions_df.empty:
                    position_count = len(positions_df)

                # Publish MTM update event for all listeners
                self.events.publish(
                    Event.MTM_UPDATE,
                    {
                        "pnl": pnl,
                        "position_count": position_count,
                        "timestamp": utils.now_ist().isoformat(),
                    },
                )

                self.log.info(
                    "%s MTM: %s | Positions: %d",
                    utils.pnl_emoji(pnl),
                    utils.fmt_rupees(pnl),
                    position_count,
                )

                # Alert on negative MTM beyond threshold
                if alert_on_negative and pnl <= alert_threshold:
                    # Avoid spamming — only alert once per threshold level
                    alert_level = int(pnl // 1000) * 1000
                    if alert_level != _last_alert_pnl:
                        _last_alert_pnl = alert_level
                        self.log.warning(
                            "🔴 MTM ALERT — %s (threshold: %s)",
                            utils.fmt_rupees(pnl),
                            utils.fmt_rupees(alert_threshold),
                        )
                        self.events.publish(
                            Event.MTM_ALERT,
                            {
                                "pnl": pnl,
                                "threshold": alert_threshold,
                            },
                        )

            except Exception as exc:
                self.log.error("Monitor check error: %s", exc)

            if self._sleep(report_interval):
                return

    def get_position_summary(self) -> dict[str, Any]:
        """Build a human-readable position summary (for Telegram)."""
        try:
            pnl = self.broker.get_live_pnl()
            balance = self.broker.get_balance()
            positions = self.broker.get_positions()

            legs = []
            if positions is not None and not positions.empty:
                for _, row in positions.iterrows():
                    symbol = row.get("tradingSymbol", row.get("tradingsymbol", "?"))
                    net_qty = int(row.get("netQty", 0))
                    pnl_leg = float(row.get("realizedProfit", 0)) + float(
                        row.get("unrealizedProfit", 0)
                    )
                    legs.append(
                        {
                            "symbol": symbol,
                            "qty": net_qty,
                            "pnl": pnl_leg,
                        }
                    )

            return {
                "pnl": pnl,
                "balance": balance,
                "legs": legs,
                "leg_count": len(legs),
                "timestamp": utils.now_ist().isoformat(),
            }
        except Exception as exc:
            return {"error": str(exc)}
