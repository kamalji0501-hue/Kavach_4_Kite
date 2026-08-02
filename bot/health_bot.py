"""
Batman v3 — Health Check Bot.

A dedicated Telegram bot that keeps you informed about system health
throughout the trading day.  It is completely independent of the main
trading bot — it has its own token and chat_id, and never places or
manages any orders.

Behaviour
---------
• **Morning greeting** — At ``start_time`` (default 08:45 IST) sends a
  "Good morning" message with a full health report.
• **EOD message** — At ``end_time`` (default 15:45 IST) sends a market-
  close summary.
• **Always listening** — ``/health`` and ``/ping`` work 24 × 7.
• **Never intrusive** — Outside the working window the bot does not send
  any proactive notifications.

Health checks performed
-----------------------
1. System — Python version, OS, current IST time
2. Broker Auth — connection state, token age
3. Market Data — live NIFTY LTP (end-to-end data feed test)
4. Balance — available margin (confirms full API chain)

Configuration (settings.json → health_bot)
------------------------------------------
    bot_token               ${HEALTH_BOT_TOKEN}
    chat_id                 ${HEALTH_CHAT_ID}
    start_time              "08:45"   (IST, HH:MM)
    end_time                "15:45"   (IST, HH:MM)
    check_interval_seconds  3600      (periodic re-check during window)
    enabled                 true
"""

from __future__ import annotations

import asyncio
import logging
import platform
import sys
import threading
import time as _time
from datetime import datetime, time
from typing import TYPE_CHECKING

from telegram.ext import Application, CommandHandler, ContextTypes

from core.utils import now_ist
from telegram import Update

if TYPE_CHECKING:
    from core.broker import BatmanBroker
    from core.config import Config

logger = logging.getLogger("batman.health_bot")


# ─────────────────────────────────────────────────────────────────────────────
# HealthBot
# ─────────────────────────────────────────────────────────────────────────────


class HealthBot:
    """
    Health-check Telegram bot.

    Usage::

        bot = HealthBot(config=config, broker=broker)
        bot.start()   # builds Application, starts polling + scheduler
        ...
        bot.stop()    # graceful shutdown
    """

    def __init__(self, config: Config, broker: BatmanBroker | None = None):
        self.config = config
        self.broker = broker

        self._token: str = config.get("health_bot.bot_token", "")
        self._chat_id: str = str(config.get("health_bot.chat_id", ""))
        self._start_time: str = config.get("health_bot.start_time", "08:45")
        self._end_time: str = config.get("health_bot.end_time", "15:45")
        self._check_interval: int = int(config.get("health_bot.check_interval_seconds", 3600))

        self._app: Application | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._polling_thread: threading.Thread | None = None
        self._scheduler_thread: threading.Thread | None = None

        # Set once the Telegram app is built and polling has started.
        # The scheduler waits on this before trying to push any messages.
        self._ready = threading.Event()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the health bot (polling + scheduler) in background threads."""
        if not self._token or not self._chat_id:
            logger.warning("Health bot disabled — missing HEALTH_BOT_TOKEN or HEALTH_CHAT_ID")
            return

        self._polling_thread = threading.Thread(
            target=self._run_polling, daemon=True, name="health-bot-poll"
        )
        self._polling_thread.start()

        self._scheduler_thread = threading.Thread(
            target=self._run_scheduler, daemon=True, name="health-bot-sched"
        )
        self._scheduler_thread.start()

        logger.info(
            "Health bot started ✓  window=%s – %s IST",
            self._start_time,
            self._end_time,
        )

    def stop(self) -> None:
        """Stop the health bot gracefully."""
        if self._app and self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._app.stop(), self._loop)
        if self._polling_thread:
            self._polling_thread.join(timeout=10)
        logger.info("Health bot stopped")

    @property
    def is_running(self) -> bool:
        return self._polling_thread is not None and self._polling_thread.is_alive()

    # ── Health checks ─────────────────────────────────────────────────────────

    def run_health_check(self) -> dict[str, dict]:
        """
        Execute all health probes and return a structured results dict.

        Return shape::

            {
                "system":      {"ok": True,  "detail": "Python 3.12 | ..."},
                "broker_auth": {"ok": True,  "detail": "Connected | Token age: 2h"},
                "market_data": {"ok": True,  "detail": "NIFTY @ 24,500.00"},
                "balance":     {"ok": True,  "detail": "₹1,50,000.00 available"},
            }
        """
        results: dict[str, dict] = {}

        # 1. System
        try:
            now = now_ist()
            results["system"] = {
                "ok": True,
                "detail": (
                    f"Python {sys.version.split()[0]} | "
                    f"{platform.system()} {platform.machine()} | "
                    f"IST {now.strftime('%H:%M:%S')}"
                ),
            }
        except Exception as exc:
            results["system"] = {"ok": False, "detail": str(exc)}

        # 2. Broker auth
        if self.broker is None:
            results["broker_auth"] = {
                "ok": False,
                "detail": "Broker not connected",
            }
        else:
            try:
                needs_refresh = self.broker.needs_reauth()
                token_age_min = (datetime.now() - self.broker._auth_time).seconds // 60
                results["broker_auth"] = {
                    "ok": True,
                    "detail": (
                        f"Connected | Token age: {token_age_min}m"
                        + (" | refresh soon" if needs_refresh else " | fresh")
                    ),
                }
            except Exception as exc:
                results["broker_auth"] = {"ok": False, "detail": str(exc)}

        # 3. Market data — NIFTY LTP
        if self.broker is None:
            results["market_data"] = {
                "ok": False,
                "detail": "Broker not available",
            }
        else:
            try:
                ltp = self.broker.get_nifty_ltp()
                results["market_data"] = {
                    "ok": ltp > 0,
                    "detail": f"NIFTY @ {ltp:,.2f}",
                }
            except Exception as exc:
                results["market_data"] = {"ok": False, "detail": str(exc)}

        # 4. Balance
        if self.broker is None:
            results["balance"] = {
                "ok": False,
                "detail": "Broker not available",
            }
        else:
            try:
                bal = self.broker.get_balance()
                results["balance"] = {
                    "ok": True,
                    "detail": f"Rs {float(bal):,.2f} available",
                }
            except Exception as exc:
                results["balance"] = {"ok": False, "detail": str(exc)}

        return results

    def _format_health_report(
        self,
        results: dict[str, dict],
        title: str = "Health Check",
    ) -> str:
        """Format health check results as a Telegram Markdown message."""
        labels = {
            "system": "System",
            "broker_auth": "Broker Auth",
            "market_data": "Market Data (NIFTY LTP)",
            "balance": "Balance",
        }
        now_str = now_ist().strftime("%d-%b-%Y %H:%M:%S IST")

        lines = [f"*{title}*", f"_{now_str}_", ""]

        all_ok = True
        for key, label in labels.items():
            r = results.get(key, {"ok": False, "detail": "Not checked"})
            marker = "✅" if r["ok"] else "❌"
            if not r["ok"]:
                all_ok = False
            lines.append(f"{marker} *{label}*")
            lines.append(f"   `{r['detail']}`")
            lines.append("")

        summary = (
            "✅ All systems OK" if all_ok else "❌ One or more checks failed — please investigate"
        )
        lines.append(f"*Status:* {summary}")
        return "\n".join(lines)

    # ── Scheduler (runs in its own thread) ───────────────────────────────────

    def _run_scheduler(self) -> None:
        """
        Background thread that:
          - Waits for the Telegram app to be ready
          - At start_time  → sends morning greeting + health report (once/day)
          - During window  → optional periodic health re-check
          - At end_time    → sends EOD summary (once/day)
        Polls every 30 seconds so timing is accurate to within half a minute.
        """
        # Wait for polling to be ready (max 60 seconds)
        if not self._ready.wait(timeout=60):
            logger.warning("Health bot: scheduler timed-out waiting for ready signal")
            return

        morning_sent_date = None
        eod_sent_date = None
        last_periodic_check: datetime | None = None

        while True:
            try:
                now = now_ist()
                today = now.date()
                current_t = now.time()
                start_t = time.fromisoformat(self._start_time)
                end_t = time.fromisoformat(self._end_time)

                in_window = start_t <= current_t <= end_t

                # Morning greeting — once per calendar day at start_time
                if current_t >= start_t and morning_sent_date != today:
                    morning_sent_date = today
                    self._push_message(self._build_morning_message())

                # EOD message — once per calendar day at end_time
                if current_t >= end_t and eod_sent_date != today:
                    eod_sent_date = today
                    self._push_message(self._build_eod_message())

                # Periodic health re-check during the working window
                if in_window and self._check_interval > 0:
                    if last_periodic_check is None or (
                        (now - last_periodic_check).total_seconds() >= self._check_interval
                    ):
                        # Skip if it coincides with the morning greeting
                        if morning_sent_date == today and last_periodic_check is None:
                            last_periodic_check = now  # mark first run
                        else:
                            last_periodic_check = now
                            results = self.run_health_check()
                            report = self._format_health_report(results, "Health Update")
                            self._push_message(report)

            except Exception as exc:
                logger.error("Health bot scheduler error: %s", exc)

            _time.sleep(30)  # resolution: 30 seconds

    def _build_morning_message(self) -> str:
        results = self.run_health_check()
        report = self._format_health_report(results, "Morning Health Check")
        return (
            f"*Batman v3 — Good Morning!*\n"
            f"Working window: {self._start_time} – {self._end_time} IST\n\n" + report
        )

    def _build_eod_message(self) -> str:
        results = self.run_health_check()
        report = self._format_health_report(results, "EOD Summary")
        return "*Batman v3 — Market Closed*\n" "Session complete for today.\n\n" + report

    def _push_message(self, text: str) -> None:
        """
        Push a message to Telegram from the scheduler thread.
        Uses run_coroutine_threadsafe so we can call from a non-async context.
        """
        if not self._loop or not self._app:
            logger.warning("Health bot: cannot push message — app not ready")
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._send_message(text), self._loop)
            future.result(timeout=20)
        except Exception as exc:
            logger.error("Health bot: push_message failed: %s", exc)

    # ── Telegram polling (runs in its own thread) ────────────────────────────

    def _run_polling(self) -> None:
        """Entry point for the polling background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._build_and_run())
        except Exception:
            logger.exception("Health bot polling crashed")
        finally:
            self._loop.close()

    async def _build_and_run(self) -> None:
        """Build the Application, register handlers, start polling."""
        self._app = Application.builder().token(self._token).build()

        # Store references for command handlers
        self._app.bot_data["chat_id"] = self._chat_id
        self._app.bot_data["health_bot_instance"] = self

        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("health", self._cmd_health))
        self._app.add_handler(CommandHandler("ping", self._cmd_ping))

        async with self._app:
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            logger.info("Health bot polling started — listening for commands …")

            # Signal scheduler that we are ready
            self._ready.set()

            # Keep alive
            stop_event = asyncio.Event()
            try:
                await stop_event.wait()
            except asyncio.CancelledError:
                pass
            finally:
                await self._app.updater.stop()
                await self._app.stop()

    # ── Async helpers ─────────────────────────────────────────────────────────

    async def _send_message(self, text: str) -> None:
        """Send a Markdown message to the configured chat_id."""
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.error("Health bot send_message error: %s", exc)

    # ── Command handlers ──────────────────────────────────────────────────────

    @staticmethod
    async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, context):
            return
        hb: HealthBot = context.bot_data.get("health_bot_instance")
        window = f"{hb._start_time} – {hb._end_time} IST" if hb else "n/a"
        await update.message.reply_text(
            f"*Batman v3 — Health Bot*\n\n"
            f"I monitor system health and notify you at market open/close.\n"
            f"Working window: `{window}`\n\n"
            f"Use /help to see available commands.",
            parse_mode="Markdown",
        )

    @staticmethod
    async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, context):
            return
        await update.message.reply_text(
            "*Health Bot Commands*\n\n"
            "/health — Run full health check now\n"
            "/ping   — Quick connectivity ping\n"
            "/start  — Show info and working window\n"
            "/help   — This message",
            parse_mode="Markdown",
        )

    @staticmethod
    async def _cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, context):
            return
        hb: HealthBot | None = context.bot_data.get("health_bot_instance")
        if hb is None:
            await update.message.reply_text("Health bot not initialized.")
            return
        await update.message.reply_text("Running health check…")
        results = hb.run_health_check()
        report = hb._format_health_report(results)
        await update.message.reply_text(report, parse_mode="Markdown")

    @staticmethod
    async def _cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update, context):
            return
        now = now_ist()
        await update.message.reply_text(
            f"*Pong!*\n`{now.strftime('%Y-%m-%d %H:%M:%S IST')}`",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Authorization helper (module-level so it can be called from static methods)
# ─────────────────────────────────────────────────────────────────────────────


def _authorized(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """Return True only if the message comes from the configured chat_id."""
    authorized_id = str(context.bot_data.get("chat_id", ""))
    user_chat_id = str(update.effective_chat.id) if update.effective_chat else ""

    if not authorized_id or user_chat_id != authorized_id:
        logger.warning(
            "Health bot: unauthorized access from chat_id=%s (expected %s)",
            user_chat_id,
            authorized_id,
        )
        if update.effective_message:
            # Fire-and-forget — we can't await in a sync function
            asyncio.ensure_future(update.effective_message.reply_text("Unauthorized."))
        return False
    return True
