"""
Batman v3 — Always-on Telegram Bot Manager.

Creates a single ``python-telegram-bot`` Application that listens
for commands 24/7.  Handler modules (ato, deploy, hedge, monitor,
admin) register their commands during init.

The bot runs as an asyncio polling task — it NEVER stops listening
as long as the program is alive.

All commands are restricted to the configured ``chat_id`` for security.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.auth import authorized_only  # noqa: F401 — re-exported for convenience
from bot.handlers.admin_handler import register_admin_handlers
from bot.handlers.ato_handler import register_ato_handlers
from bot.handlers.deploy_handler import register_deploy_handlers
from bot.handlers.hedge_handler import register_hedge_handlers
from bot.handlers.monitor_handler import register_monitor_handlers
from telegram import Update

if TYPE_CHECKING:
    from core.broker import BatmanBroker
    from core.config import Config
    from core.event_bus import EventBus
    from core.state import StateManager

logger = logging.getLogger("batman.telegram")


class BotManager:
    """Wraps python-telegram-bot Application in a background thread.

    Usage::

        bot = BotManager(token, chat_id, modules_dict, broker, config, state, events)
        bot.start()       # starts polling in background thread
        ...
        bot.stop()        # graceful shutdown
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        modules: dict,
        broker: BatmanBroker,
        config: Config,
        state: StateManager,
        events: EventBus,
    ):
        self.token = token
        self.chat_id = str(chat_id)
        self.modules = modules
        self.broker = broker
        self.config = config
        self.state = state
        self.events = events

        self._app: Application | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Set after construction (to avoid circular dependency)
        self._shutdown_event: threading.Event | None = None
        self._scheduler = None  # AlgoScheduler set via set_scheduler()

    # ── External wiring ──────────────────────────────────────

    def set_shutdown_event(self, event: threading.Event) -> None:
        """Register the threading.Event that /shutdown will signal."""
        self._shutdown_event = event
        if self._app:
            self._app.bot_data["shutdown_event"] = event

    def set_scheduler(self, scheduler) -> None:
        """Register the AlgoScheduler so the algo_confirm callback can reach it."""
        self._scheduler = scheduler
        if self._app:
            self._app.bot_data["algo_scheduler"] = scheduler

    # ── Lifecycle ────────────────────────────────────────────

    def start(self) -> None:
        """Build the Application, register handlers, and start polling
        in a dedicated daemon thread."""
        self._thread = threading.Thread(target=self._run_polling, daemon=True, name="telegram-bot")
        self._thread.start()
        logger.info("Telegram bot started (polling)")

    def stop(self) -> None:
        """Stop the bot gracefully."""
        if self._app and self._loop:
            asyncio.run_coroutine_threadsafe(self._app.stop(), self._loop)
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Telegram bot stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Internal ─────────────────────────────────────────────

    def _run_polling(self) -> None:
        """Entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._build_and_run())
        except Exception:
            logger.exception("Telegram bot crashed")
        finally:
            self._loop.close()

    async def _build_and_run(self) -> None:
        """Build the Application, register handlers, start polling."""
        builder = Application.builder().token(self.token)
        self._app = builder.build()

        # Inject shared context into bot_data for handlers to access
        self._app.bot_data["broker"] = self.broker
        self._app.bot_data["config"] = self.config
        self._app.bot_data["state"] = self.state
        self._app.bot_data["events"] = self.events
        self._app.bot_data["modules"] = self.modules
        self._app.bot_data["chat_id"] = self.chat_id

        # Wire optional components that may have been set before start()
        if self._shutdown_event:
            self._app.bot_data["shutdown_event"] = self._shutdown_event
        if self._scheduler:
            self._app.bot_data["algo_scheduler"] = self._scheduler

        # ── Register all handler groups ──────────────────────
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))

        register_ato_handlers(self._app)
        register_deploy_handlers(self._app)
        register_hedge_handlers(self._app)
        register_monitor_handlers(self._app)
        register_admin_handlers(self._app)

        # ── Algo daily time-selection callback ──────────────
        self._app.add_handler(CallbackQueryHandler(self._cb_algo_time, pattern=r"^algo_time:"))

        logger.info("All Telegram handlers registered")

        # Start polling — this blocks until stopped
        async with self._app:
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot listening …")

            # Keep alive until stopped
            stop_event = asyncio.Event()
            try:
                await stop_event.wait()
            except asyncio.CancelledError:
                pass
            finally:
                await self._app.updater.stop()
                await self._app.stop()

    # ── Algo time-selection callback ────────────────────────

    @staticmethod
    @authorized_only
    async def _cb_algo_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle time-slot selection from the daily algo start-time keyboard."""
        query = update.callback_query
        await query.answer()

        time_str = query.data.split(":", 1)[1]  # e.g. "09:20"
        scheduler = context.bot_data.get("algo_scheduler")

        if scheduler is None:
            await query.edit_message_text("⚠ Scheduler not available.")
            return

        await query.edit_message_text(
            f"⏰ *Algo start time set: {time_str} IST*",
            parse_mode="Markdown",
        )

        # Delegate all logic to the scheduler
        scheduler.handle_time_selection(time_str)

    # ── Base commands ────────────────────────────────────────

    @staticmethod
    @authorized_only
    async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "🦇 *Batman v3 — Online*\n\n" "Use /help to see available commands.",
            parse_mode="Markdown",
        )

    @staticmethod
    @authorized_only
    async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            "🦇 *Batman v3 Commands*\n\n"
            "*ATO Protection:*\n"
            "/ato — Select ATO exit points\n\n"
            "*Deployment:*\n"
            "/choose — Choose your 4 Batman legs\n"
            "/batman\\_complete — Batman complete — reset algo\n"
            "/close\\_all — Close all positions\n\n"
            "*Hedging:*\n"
            "/hedge — Place overnight hedge\n"
            "/close\\_hedge — Close hedge\n\n"
            "*Monitoring:*\n"
            "/status — System & module status\n"
            "/legs — Batman open legs\n"
            "/pnl — Live P&L\n"
            "/funds — Available funds\n\n"
            "*Admin:*\n"
            "/modules — List all modules\n"
            "/enable `<module>` — Enable a module\n"
            "/disable `<module>` — Disable a module\n"
            "/exit — Emergency exit all positions\n\n"
            "*Algo Control:*\n"
            "/pause — Pause algo (positions stay open)\n"
            "/resume — Resume algo within trading window\n"
            "/start\\_now — Force-start algo immediately\n"
            "/algo\\_status — Show today's algo state\n\n"
            "*System:*\n"
            "/shutdown — Graceful process exit (no position close)"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
