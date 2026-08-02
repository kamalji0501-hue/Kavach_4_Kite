"""
Batman v3 — LAKSHMI Bot (लक्ष्मी)

Bot 3 of 3.  Runs as an asyncio task inside ``main.py``.

Responsibilities (LOCKED 2026-04-04):
    • /pnl    — live P&L breakdown across all 4 Batman positions (on demand)
    • /status — monitoring status: MTM, ATO state, deployment, NIFTY spot
    • Proactive MTM loss alerts  — fires IMMEDIATELY when threshold is breached
    • Proactive profit target alerts — fires when cumulative MTM hits target
    • Trailing stop alerts — trailing activated, trailing stop hit, hard stop hit
    • End-of-day P&L summary at 15:35 IST (configurable in params.json)

Does NOT own: trading commands (/register, /exit, etc.), token management,
broker health, ATO trigger control.
"""

from __future__ import annotations

import asyncio
import json
import logging
import zoneinfo
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bat_telegram.loader import load_bot_config
from telegram import Message, Update

logger = logging.getLogger("batman.lakshmi")

_DEPLOY_DIR = Path("data/deployments")

# Help text (MarkdownV2)
_HELP = (
    "💰 *LAKSHMI — Available Commands*\n\n"
    "/pnl     — Live MTM P&L breakdown table\n"
    "/status  — Monitoring & ATO status"
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _find_active_deployment() -> dict | None:
    """Load and return the active deployment JSON, or None if not found."""
    files = sorted(_DEPLOY_DIR.glob("batman_*.json"))
    if not files:
        return None
    try:
        with open(files[-1], encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return None
        return cast(dict[str, Any], data)
    except Exception:
        return None


def _escape_md(text: str) -> str:
    """Escape characters that have special meaning in MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


def _require_message(update: Update) -> Message:
    message = update.message
    if message is None:
        raise ValueError("Telegram update is missing a message")
    return message


# ═══════════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════════


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await message.reply_text(
        "💰 *LAKSHMI — P&L & MTM Bot*\n\n"
        "I watch your Batman positions and alert you on loss thresholds and profit targets\\.\n\n"
        + _HELP,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Live P&L breakdown across all 4 Batman legs."""
    message = _require_message(update)
    dep = _find_active_deployment()
    if not dep:
        await message.reply_text(
            "⚠️ No active deployment\\.\n\nP&L is only available when Batman is armed\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    broker = context.bot_data.get("broker")
    if not broker:
        await message.reply_text(
            "⚠️ No broker connection\\.\n\nSend a Dhan token to DRISHTI first\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        total_pnl = broker.get_live_pnl()
    except Exception as exc:
        await message.reply_text(
            f"⚠️ Could not fetch P&L from broker: {_escape_md(str(exc))}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    dep_positions = dep.get("positions", {})
    state = context.bot_data.get("state")
    ce_trig = state.get("ato.ce_triggered", False) if state else False
    pe_trig = state.get("ato.pe_triggered", False) if state else False
    ato_str = "🔴 CE TRIGGERED" if ce_trig else "🔴 PE TRIGGERED" if pe_trig else "🟢 IDLE"

    now = datetime.now().strftime("%d-%b-%Y · %H:%M IST")

    # Build a monospace breakdown per deployment leg
    # Individual leg P&L is not always available from all broker APIs in
    # a simple way; we show the leg symbols and the total P&L from the broker.
    order = [
        ("pe_buy", "PE BUY "),
        ("pe_sell", "PE SELL"),
        ("ce_sell", "CE SELL"),
        ("ce_buy", "CE BUY "),
    ]

    rows = []
    for key, label in order:
        leg = dep_positions.get(key, {})
        sym = leg.get("symbol", "N/A")
        rows.append(f"  {label}  {sym}")

    sign = "🟢" if total_pnl >= 0 else "🔴"
    pnl_formatted = f"₹{total_pnl:+,.2f}"

    body = (
        f"📊 MTM — {now}\n"
        "─" * 42 + "\n" + "\n".join(rows) + "\n" + "─" * 42 + "\n"
        f"  Total P&L   : {pnl_formatted}  {sign}\n"
        f"  ATO Status  : {ato_str}"
    )

    await message.reply_text(f"```\n{body}\n```", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Monitoring status — MTM, ATO, deployment, NIFTY spot."""
    message = _require_message(update)
    dep = _find_active_deployment()
    broker = context.bot_data.get("broker")
    state = context.bot_data.get("state")

    dep_line = "✅ Armed" if dep else "⏳ No deployment"
    ce_trig = state.get("ato.ce_triggered", False) if state else False
    pe_trig = state.get("ato.pe_triggered", False) if state else False

    pnl_line = "N/A"
    spot_line = "N/A"

    if broker:
        try:
            spot = broker.get_nifty_ltp()
            spot_line = f"₹{spot:,.2f}"
        except Exception:
            spot_line = "⚠️ Could not fetch"

        if dep:
            try:
                pnl = broker.get_live_pnl()
                sign = "🟢" if pnl >= 0 else "🔴"
                pnl_line = f"₹{pnl:+,.2f}  {sign}"
            except Exception:
                pnl_line = "⚠️ Could not fetch"

    ato_line = "🔴 ACTIVE" if (ce_trig or pe_trig) else "🟢 Idle"

    await message.reply_text(
        f"💰 *LAKSHMI Status*\n\n"
        f"Monitoring : {dep_line}\n"
        f"NIFTY      : {spot_line}\n"
        f"MTM        : {pnl_line}\n"
        f"ATO        : {ato_line}",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """hello/hi greeting and unknown command catch-all."""
    message = _require_message(update)
    text = (message.text or "").strip()
    if text.lower() in ("hello", "hi"):
        await message.reply_text(
            "💰 Hello\\! I'm *LAKSHMI*, your P&L & MTM bot\\.\n\n" + _HELP,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    prefix = f"❌ Unknown: `{text}`\n\n" if text.startswith("/") else ""
    await message.reply_text(prefix + _HELP, parse_mode=ParseMode.MARKDOWN_V2)


# ═══════════════════════════════════════════════════════════════════════════════
# Proactive alerts — EventBus subscriptions
# ═══════════════════════════════════════════════════════════════════════════════


async def _push(app: Application, chat_id: str, text: str) -> None:
    """Send a proactive alert to the LAKSHMI chat (MarkdownV2)."""
    try:
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as exc:
        logger.error("LAKSHMI push notification failed: %s", exc)


def register_event_subscriptions(app: Application) -> None:
    """Subscribe to EventBus events for proactive MTM / trailing alerts.

    Called from build_application after bot_data is populated.

    Thread-safety note: EventBus callbacks are invoked from module *threads*.
    We use ``asyncio.run_coroutine_threadsafe(coro, loop)`` (stored in
    bot_data["loop"] by main.py) to schedule Telegram messages safely into
    the main asyncio event loop.
    """
    bus = app.bot_data.get("event_bus")
    chat_id = app.bot_data.get("chat_id", "")
    if not bus or not chat_id:
        logger.warning("LAKSHMI: event_bus or chat_id missing — skipping subscriptions")
        return

    from core.event_bus import Event

    def _fire(coro) -> None:
        """Dispatch *coro* into the main asyncio loop from any thread."""
        _loop = app.bot_data.get("loop")
        if _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, _loop)
        else:
            logger.warning("LAKSHMI: event loop not available — push skipped")

    def _on_mtm_alert(event, payload):
        mtm_val = payload.get("mtm", "?")
        threshold = payload.get("threshold", "?")
        try:
            mtm_str = f"₹{float(mtm_val):+,.2f}"
            thr_str = f"₹{float(threshold):,.2f}"
        except (TypeError, ValueError):
            mtm_str = str(mtm_val)
            thr_str = str(threshold)
        _fire(
            _push(
                app,
                chat_id,
                f"🔴 *MTM Loss Alert*\n\n"
                f"MTM       : {_escape_md(mtm_str)}\n"
                f"Threshold : {_escape_md(thr_str)}\n\n"
                f"Send /pnl for full breakdown\\.",
            )
        )

    def _on_profit_target(event, payload):
        pnl_val = payload.get("pnl", "?")
        try:
            pnl_str = f"₹{float(pnl_val):+,.2f}"
        except (TypeError, ValueError):
            pnl_str = str(pnl_val)
        _fire(
            _push(
                app,
                chat_id,
                f"🎯 *Profit Target Hit\\!*\n\n"
                f"MTM : {_escape_md(pnl_str)}\n\n"
                f"Consider running /batman\\_complete if done for the day\\.",
            )
        )

    def _on_trailing_activated(event, payload):
        _fire(
            _push(
                app,
                chat_id,
                "📈 *Trailing Stop Activated*\n\n"
                "Profit trailing is now active — locking in gains\\.",
            )
        )

    def _on_trailing_stop_hit(event, payload):
        _fire(
            _push(
                app,
                chat_id,
                "⛔ *Trailing Stop Hit*\n\n"
                "Exit triggered by trailing stop\\. Send /pnl for final P&L\\.",
            )
        )

    def _on_hard_stop_hit(event, payload):
        _fire(
            _push(
                app,
                chat_id,
                "🚨 *Hard Stop Hit\\!*\n\n"
                "Maximum loss threshold breached\\. Emergency stop triggered\\.\n"
                "Check KAVACH for position status\\.",
            )
        )

    bus.subscribe(Event.MTM_ALERT, _on_mtm_alert)
    bus.subscribe(Event.PROFIT_TARGET_HIT, _on_profit_target)
    bus.subscribe(Event.TRAILING_ACTIVATED, _on_trailing_activated)
    bus.subscribe(Event.TRAILING_STOP_HIT, _on_trailing_stop_hit)
    bus.subscribe(Event.HARD_STOP_HIT, _on_hard_stop_hit)

    logger.info("LAKSHMI: event subscriptions registered ✓")


# ═══════════════════════════════════════════════════════════════════════════════
# Background coroutines
# ═══════════════════════════════════════════════════════════════════════════════

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


async def _eod_summary_loop(app: Application) -> None:
    """Send the EOD P&L summary at the configured time (default 15:35 IST).

    Fires once per trading day, weekdays only. Uses a ``last_sent_date`` guard
    so a process restart won’t send a duplicate.

    Design spec: lakshmi_design.md §'EOD P&L Summary'.
    """
    params = app.bot_data.get("params", {})
    eod_cfg = params.get("pnl_report", {})
    eod_str = eod_cfg.get("eod_time", "15:35")
    send_eod = eod_cfg.get("send_eod_report", True)
    chat_id = app.bot_data.get("chat_id", "")

    eod_h, eod_m = (int(x) for x in eod_str.split(":"))
    last_sent_date = None

    while True:
        await asyncio.sleep(60)
        try:
            if not send_eod or not chat_id:
                continue

            now_ist = datetime.now(_IST)

            # Weekdays only
            if now_ist.weekday() >= 5:
                continue

            # Time gate
            t = now_ist.time()
            if not (t.hour == eod_h and t.minute == eod_m):
                continue

            # Once-per-day guard
            today = now_ist.date()
            if last_sent_date == today:
                continue

            dep = _find_active_deployment()
            if not dep:
                continue  # No active deployment — nothing to report

            broker = app.bot_data.get("broker")
            last_sent_date = today  # mark before await to prevent double-fire

            pnl_str = "N/A"
            if broker:
                try:
                    pnl = broker.get_live_pnl()
                    sign = "🟢" if pnl >= 0 else "🔴"
                    pnl_str = f"₹{pnl:+,.2f}  {sign}"
                except Exception:
                    pnl_str = "⚠️ Could not fetch"

            date_str = now_ist.strftime("%d\\-%b\\-%Y")
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"📊 *EOD P&L Summary \u2014 {date_str}*\n\n"
                    f"Final MTM : {pnl_str}\n\n"
                    f"_Market closed\\. Use /pnl for a detailed breakdown\\._\n"
                    f"_Run /batman\\_complete in KAVACH to close this session\\._"
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            logger.info("LAKSHMI: EOD P&L summary sent for %s", today)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("LAKSHMI EOD summary loop error: %s", exc)


async def _lakshmi_post_init(application: Application) -> None:
    """Start LAKSHMI background coroutines after PTB Application.initialize()."""
    asyncio.create_task(_eod_summary_loop(application))
    logger.info("LAKSHMI: EOD summary loop started ✓")


# ═══════════════════════════════════════════════════════════════════════════════
# Bot builder — called from main.py
# ═══════════════════════════════════════════════════════════════════════════════


def build_application(broker=None, state=None, event_bus=None) -> Application:
    """Build and return the LAKSHMI PTB Application.

    Inject ``broker``, ``state``, and ``event_bus`` so all handlers can
    reach shared runtime objects via ``context.bot_data``.

    Usage (from main.py)::

        from bat_telegram.bots.lakshmi import bot as lakshmi_bot
        app = lakshmi_bot.build_application(broker=broker, state=state, event_bus=bus)
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        ...
        await app.updater.stop()
        await app.stop()
    """
    cfg = load_bot_config("lakshmi")
    params = cfg.params

    app = Application.builder().token(cfg.bot_token).post_init(_lakshmi_post_init).build()

    # Inject shared objects
    app.bot_data["broker"] = broker
    app.bot_data["state"] = state
    app.bot_data["event_bus"] = event_bus
    app.bot_data["chat_id"] = cfg.chat_id
    app.bot_data["params"] = params

    # ── Commands ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    app.add_handler(CommandHandler("status", cmd_status))

    # ── Catch-all plain-text handler (hello / invalid) ────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # ── Subscribe to EventBus for proactive alerts ────────────────────────────
    register_event_subscriptions(app)

    logger.info("LAKSHMI bot application built ✓")
    return app
