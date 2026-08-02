"""
Batman v3 — Daily Algo Scheduler.

Manages the lifecycle of automated trading modules each day:

  1. At ``prompt_time`` (09:00 IST) — sends a Telegram inline keyboard asking
     *"What time should I start the algo today?"* with preset time slots.
     Skipped entirely when ``deployment.batman_complete`` is True, or
     when ``deployment.confirmed`` is False.
  2. User taps a time slot (e.g. 09:20) — stored as the selected start time.
  3. At the selected start time — auto-starts all configured algo modules.
  4. On timeout (no response in ``confirm_timeout_minutes``) — no algo today.
  5. At ``end_time`` (15:30 IST) — automatically stops all algo modules.
  6. ``/pause`` / ``/resume`` — pause/resume on demand.
  7. Daily state resets automatically after midnight.

Callback data tokens (used by BotManager to route responses):
    ``algo_time:HH:MM``  — time slot chosen by user (e.g. ``algo_time:09:20``)

Configuration path: settings.json → operations.*
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time as _time
from collections.abc import Callable
from datetime import date, datetime, time

from core.utils import is_expiry_day, now_ist
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("batman.scheduler")

# Callback token prefix — shared with BotManager's CallbackQueryHandler
CALLBACK_ALGO_TIME_PREFIX = "algo_time:"

# Default algo modules: started/stopped by the scheduler.
# "Always-on" modules (position_monitor, emergency_exit) are NOT in this list.
# batman_entry and overnight_hedge are OUT OF SCOPE — manual deploy only.
_DEFAULT_ALGO_MODULES: list[str] = [
    "ato_protection",
    "profit_trailing",
]

_DEFAULT_ALWAYS_ON: list[str] = [
    "position_monitor",
    "emergency_exit",
]

_DEFAULT_TIME_OPTIONS: list[str] = [
    "09:20",
    "09:25",
    "09:30",
    "09:35",
    "09:40",
    "09:45",
    "10:00",
    "10:15",
    "10:30",
    "11:00",
]


class AlgoScheduler:
    """
    Daily algo lifecycle scheduler.

    Usage::

        scheduler = AlgoScheduler(
            modules=module_instances,
            config=config,
            state=state,
            loop_getter=lambda: telegram_bot._loop,
            app_getter=lambda: telegram_bot._app,
            chat_id=chat_id,
        )
        scheduler.start()   # starts background thread (30-second ticks)
        ...
        scheduler.stop()    # graceful shutdown

    After construction, call ``telegram_bot.set_scheduler(scheduler)``
    so the BotManager can route algo_time:* callbacks here.
    """

    def __init__(
        self,
        modules: dict,
        config,
        state,
        loop_getter: Callable[[], asyncio.AbstractEventLoop | None],
        app_getter: Callable,
        chat_id: str,
    ):
        self.modules = modules
        self.config = config
        self.state = state
        self._get_loop = loop_getter
        self._get_app = app_getter
        self._chat_id = str(chat_id)

        # Configurable timings
        self._prompt_time: str = config.get("operations.prompt_time", "09:00")
        self._end_time: str = config.get("operations.end_time", "15:30")
        self._timeout_min: int = int(config.get("operations.confirm_timeout_minutes", 5))
        self._algo_modules: list[str] = config.get("operations.algo_modules", _DEFAULT_ALGO_MODULES)
        self._time_options: list[str] = config.get(
            "operations.algo_start_time_options", _DEFAULT_TIME_OPTIONS
        )

        # Thread control
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # ── Daily state (reset after midnight) ──────────────
        # None = awaiting time selection; "TIMEOUT" = timed out; else "HH:MM"
        self._selected_start_time: str | None = None
        self._prompt_sent_date: date | None = None
        self._prompt_sent_time: datetime | None = None
        self._algo_started_date: date | None = None
        self._eod_stopped_date: date | None = None
        self._manually_stopped: bool = False
        self._eod_batman_complete_prompt_date: date | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler background thread."""
        self._thread = threading.Thread(target=self._loop, daemon=True, name="algo-scheduler")
        self._thread.start()
        logger.info(
            "AlgoScheduler started  prompt=%s  end=%s IST  timeout=%dm",
            self._prompt_time,
            self._end_time,
            self._timeout_min,
        )

    def stop(self) -> None:
        """Signal the scheduler to stop and wait for the thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("AlgoScheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        """Return a JSON-serializable summary for /status display."""
        batman_complete = self.state.get("deployment.batman_complete", False)
        deployed = self.state.get("deployment.confirmed", False)
        return {
            "selected_start_time": self._selected_start_time,
            "algo_started_today": self._algo_started_date is not None,
            "manually_stopped": self._manually_stopped,
            "prompt_time": self._prompt_time,
            "end_time": self._end_time,
            "prompt_sent": bool(self._prompt_sent_date),
            "batman_complete": batman_complete,
            "deployment_confirmed": deployed,
        }

    # ── External control ──────────────────────────────────────────────────────

    def handle_time_selection(self, time_str: str) -> None:
        """
        Process the user's time-slot choice from the inline keyboard.

        Called by BotManager when the user taps an ``algo_time:HH:MM`` button.
        Schedules auto-start at the chosen time.
        """
        self._selected_start_time = time_str
        logger.info("AlgoScheduler: user selected start time %s", time_str)
        self._push(
            f"✅ *Algo start scheduled for {time_str} IST*\n"
            f"Modules will start automatically at {time_str}.\n"
            f"Trading window ends at {self._end_time} IST.\n\n"
            f"Use /pause to cancel before start, or /resume after."
        )

    def stop_algo(self) -> int:
        """Stop all algo modules immediately without closing positions."""
        self._manually_stopped = True
        return self._stop_algo_modules()

    def resume_algo(self) -> tuple[bool, str]:
        """
        Attempt to resume algo after a manual stop.

        Returns (True, "N module(s) restarted") on success or (False, reason).
        """
        if not self.state.get("deployment.confirmed", False):
            return False, "Deployment not confirmed — run /deploy to register positions."

        now_t = now_ist().time()
        end_t = time.fromisoformat(self._end_time)

        if now_t >= end_t:
            return False, f"Trading window already closed ({self._end_time} IST)"

        if self._selected_start_time is None or self._selected_start_time == "TIMEOUT":
            return (
                False,
                "No start time selected today. " "Use /force\\_algo to start immediately.",
            )

        self._manually_stopped = False
        count = self._start_algo_modules()
        return True, f"{count} module(s) restarted"

    def force_confirm_yes(self) -> None:
        """
        Override: force-start algo modules immediately.
        Used when the scheduled prompt was missed or skipped.
        """
        now_t = now_ist().strftime("%H:%M")
        self._selected_start_time = now_t
        self._algo_started_date = now_ist().date()
        self._manually_stopped = False
        count = self._start_algo_modules()
        self._push(
            f"✅ *Algo force-started*\n"
            f"{count} module(s) started at {now_t} IST.\n"
            f"Trading window ends at {self._end_time} IST."
        )

    # ── Scheduler main loop ───────────────────────────────────────────────────

    def _loop(self) -> None:
        """Background thread — ticks every 30 seconds."""
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.error("AlgoScheduler tick error: %s", exc)
            self._stop_event.wait(30)

    def _tick(self) -> None:  # noqa: C901
        """Called every 30 seconds. Core scheduling logic."""
        now = now_ist()
        today = now.date()
        now_t = now.time()

        prompt_t = time.fromisoformat(self._prompt_time)
        end_t = time.fromisoformat(self._end_time)

        # ── Midnight reset ───────────────────────────────────
        if self._prompt_sent_date and self._prompt_sent_date < today:
            logger.info("AlgoScheduler: new trading day — resetting daily state")
            self._selected_start_time = None
            self._prompt_sent_date = None
            self._prompt_sent_time = None
            self._algo_started_date = None
            self._eod_stopped_date = None
            self._manually_stopped = False
            self._eod_batman_complete_prompt_date = None

        # ── Skip if batman complete or not deployed ────────────
        batman_complete = self.state.get("deployment.batman_complete", False)
        deployed = self.state.get("deployment.confirmed", False)

        if batman_complete:
            next_d = self.state.get("deployment.next_entry_date")
            logger.debug("AlgoScheduler: batman_complete=True — next cycle %s", next_d)
            return

        if not deployed:
            logger.debug("AlgoScheduler: deployment not confirmed — waiting")
            return

        # ── Send time-picker prompt at prompt_time ───────────
        if now_t >= prompt_t and self._prompt_sent_date != today:
            self._prompt_sent_date = today
            self._prompt_sent_time = datetime.now()
            self._send_time_prompt(now)

        # ── Timeout: no response → no algo today ─────────────
        if (
            self._prompt_sent_date == today
            and self._selected_start_time is None
            and self._prompt_sent_time is not None
        ):
            elapsed_min = (datetime.now() - self._prompt_sent_time).total_seconds() / 60
            if elapsed_min >= self._timeout_min:
                logger.warning("Time-picker timed out (%.1f min) — no algo today", elapsed_min)
                self._selected_start_time = "TIMEOUT"
                self._push(
                    f"⏰ *Algo start timed out ({self._timeout_min} min)*\n"
                    f"No automated trading today.\n\n"
                    f"Use /force\\_algo to start immediately within the trading window."
                )

        # ── Auto-start at selected time ───────────────────────
        if (
            self._selected_start_time
            and self._selected_start_time != "TIMEOUT"
            and self._algo_started_date != today
            and not self._manually_stopped
        ):
            start_t = time.fromisoformat(self._selected_start_time)
            if now_t >= start_t:
                self._algo_started_date = today
                count = self._start_algo_modules()
                self._push(
                    f"🚀 *Algo started — {self._selected_start_time} IST*\n"
                    f"{count} module(s) running.\n"
                    f"Trading window: {self._selected_start_time} – {self._end_time} IST"
                )

        # ── EOD auto-stop ─────────────────────────────────────
        if (
            now_t >= end_t
            and self._eod_stopped_date != today
            and self._algo_started_date == today
            and not self._manually_stopped
        ):
            self._eod_stopped_date = today
            count = self._stop_algo_modules()
            self._push(
                f"⏰ *Trading window closed ({self._end_time} IST)*\n"
                f"{count} algo module(s) stopped for the day.\n"
                f"Position monitoring continues."
            )

        # ── EOD batman_complete prompt ─────────────────────────────────────────
        # Fires once per day at EOD when Batman is deployed and not yet complete.
        # NOT restricted to Tuesday or any specific expiry day — Rahul may deploy
        # for any expiry (7 Apr, 13 Apr, 28 Apr...) and close before expiry.
        # expiry_day_name = self.config.get("strategy.expiry_day", "Tuesday")  # unused — removed
        # expiry_weekday  = day_name_to_weekday(expiry_day_name)               # unused — removed
        if (
            now_t >= end_t
            and self._eod_batman_complete_prompt_date != today
            and deployed
            and not batman_complete
            # and self._is_expiry_today(expiry_weekday)  # removed: deploy is any-day
        ):
            self._eod_batman_complete_prompt_date = today
            self._send_eod_batman_complete_prompt()

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _is_expiry_today(self, expiry_weekday: int) -> bool:
        """True if today is the weekly expiry day (0 DTE). Overrideable in tests."""
        return is_expiry_day(expiry_weekday)

    def _send_eod_batman_complete_prompt(self) -> None:
        """Send an inline-keyboard prompt asking the user to mark Batman complete."""
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Yes — Batman complete", callback_data="batman_complete:confirm"
                    ),
                    InlineKeyboardButton("❌ Not yet", callback_data="batman_complete:cancel"),
                ]
            ]
        )
        self._push_with_keyboard(
            "🦇 *Batman — Positions Complete?*\n\n"
            f"Trading window has closed ({self._end_time} IST).\n\n"
            "Are you done with this Batman deployment?\n"
            "• All deployment data cleared\n"
            "• ATO and positions reset — algo ready for next deploy\n\n"
            "_Your open positions on Dhan are NOT closed automatically._",
            keyboard,
        )

    def _send_time_prompt(self, now: datetime) -> None:
        today_str = now.strftime("%A, %d %b %Y")
        text = (
            f"🤖 *Batman v3 — Algo Start Time*\n\n"
            f"📅 {today_str}\n"
            f"Deployment confirmed ✅\n\n"
            f"What time should I start the algo today?\n\n"
            f"_No response in {self._timeout_min} min → no algo today._"
        )
        # Build 3-per-row keyboard from time options
        buttons = [
            InlineKeyboardButton(t, callback_data=f"{CALLBACK_ALGO_TIME_PREFIX}{t}")
            for t in self._time_options
        ]
        rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
        keyboard = InlineKeyboardMarkup(rows)
        self._push_with_keyboard(text, keyboard)

    # ── Module helpers ────────────────────────────────────────────────────────

    def _start_algo_modules(self) -> int:
        count = 0
        for name in self._algo_modules:
            mod = self.modules.get(name)
            if mod and mod.is_enabled() and not mod.is_running:
                mod.start()
                count += 1
                logger.info("AlgoScheduler: started module '%s'", name)
        logger.info("AlgoScheduler: started %d algo module(s)", count)
        return count

    def _stop_algo_modules(self) -> int:
        count = 0
        for name in self._algo_modules:
            mod = self.modules.get(name)
            if mod and mod.is_running:
                mod.stop()
                count += 1
                logger.info("AlgoScheduler: stopped module '%s'", name)
        logger.info("AlgoScheduler: stopped %d algo module(s)", count)
        return count

    # ── Message push helpers ──────────────────────────────────────────────────

    def _push(self, text: str, retries: int = 5) -> None:
        """Send a plain Markdown message. Retries if loop not ready yet."""
        for attempt in range(retries):
            loop = self._get_loop()
            app = self._get_app()
            if loop and app and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    app.bot.send_message(
                        chat_id=self._chat_id,
                        text=text,
                        parse_mode="Markdown",
                    ),
                    loop,
                )
                try:
                    future.result(timeout=15)
                    return
                except Exception as exc:
                    logger.error("AlgoScheduler push error (attempt %d): %s", attempt + 1, exc)
                    return
            _time.sleep(2)
        logger.error(
            "AlgoScheduler: could not push message — loop unavailable after %d retries",
            retries,
        )

    def _push_with_keyboard(self, text: str, keyboard: InlineKeyboardMarkup) -> None:
        """Send a Markdown message with an inline keyboard."""
        for attempt in range(5):
            loop = self._get_loop()
            app = self._get_app()
            if loop and app and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    app.bot.send_message(
                        chat_id=self._chat_id,
                        text=text,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    ),
                    loop,
                )
                try:
                    future.result(timeout=15)
                    return
                except Exception as exc:
                    logger.error(
                        "AlgoScheduler push_keyboard error (attempt %d): %s",
                        attempt + 1,
                        exc,
                    )
                    return
            _time.sleep(2)
        logger.error("AlgoScheduler: could not push keyboard message — loop unavailable")
