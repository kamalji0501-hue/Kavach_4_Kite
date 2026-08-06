"""
Batman v3 — JAGRAN Bot (जागरण)

Dedicated critical-incident channel. Runs standalone (run_jagran.py).

Outbound alerts from DRISHTI/KAVACH/main are delivered via incident_publisher.
This bot provides operator UI: status, recent incidents, today summary, test alert,
and a trading-day EOD digest at 15:32 IST (configurable via params.json).
"""

from __future__ import annotations

import asyncio
import html
import logging
import zoneinfo
from datetime import datetime
from datetime import time as dt_time
from typing import Any, cast

from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bat_telegram.bots.jagran.ledger import read_ledger_rows, summarize_day
from bat_telegram.incident_publisher import (
    active_incident_count,
    publish_incident,
)
from bat_telegram.loader import load_bot_config
from core.telegram_runtime import cleanup_managed_runtime, create_managed_task
from core.utils import is_trading_day
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

logger = logging.getLogger("batman.jagran")

_CB_MENU = "jag_menu"
_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def _he(text: Any) -> str:
    return html.escape(str(text), quote=False)


def _require_message(update: Update) -> Message:
    if update.message is None:
        raise ValueError("Telegram update is missing a message")
    return update.message


def _require_query(update: Update) -> CallbackQuery:
    if update.callback_query is None:
        raise ValueError("Telegram update is missing a callback query")
    return update.callback_query


def _params(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return cast(dict[str, Any], context.bot_data.get("params") or {})


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 Status", callback_data=f"{_CB_MENU}:status"),
                InlineKeyboardButton("🕒 Recent", callback_data=f"{_CB_MENU}:recent"),
            ],
            [
                InlineKeyboardButton("📅 Today", callback_data=f"{_CB_MENU}:today"),
                InlineKeyboardButton("🔔 Test Alert", callback_data=f"{_CB_MENU}:test"),
            ],
        ]
    )


async def _send_alive_menu(message: Message) -> None:
    from bat_telegram.alive_branding import reply_alive_card

    now = datetime.now(_IST).strftime("%d-%b-%Y %H:%M:%S IST")
    open_count = active_incident_count()
    await reply_alive_card(
        message,
        f"🚨 <b>JAGRAN ACTIVE</b>\n<code>{now}</code>\nOpen Incidents: <b>{open_count}</b>",
        reply_markup=_main_menu_keyboard(),
        bot_name="jagran",
    )


def _status_icon(status: str) -> str:
    s = str(status).lower()
    if any(k in s for k in ("recover", "resolved", "ok", "clear")):
        return "🟢"
    if any(k in s for k in ("fail", "trigger", "error", "critical", "down")):
        return "🔴"
    if any(k in s for k in ("suppress", "dedup", "warn")):
        return "🟡"
    return "🔵"


def _format_recent_rows(limit: int = 10) -> str:
    rows = read_ledger_rows(limit=limit)
    if not rows:
        return "🕒 <b>Recent Incidents</b>\n\n✅ No incidents recorded today."
    lines = ["🕒 <b>Recent Incidents</b>\n"]
    for row in reversed(rows):
        ts = row.get("ts_ist", "?")
        status = row.get("status_label", "?")
        source = row.get("source", "?")
        scenario = row.get("scenario", "?")
        title = row.get("title", "")
        icon = _status_icon(status)
        lines.append(
            f"{icon} <b>{_he(status)}</b> · <code>{_he(ts)}</code>\n"
            f"    <b>Source:</b> {_he(source)} / {_he(scenario)}\n"
            f"    {_he(title)}"
        )
    return "\n\n".join(lines)


def _format_today_summary() -> str:
    summary = summarize_day()
    by_source = summary.get("by_source") or {}
    src_lines = "\n".join(f"  {k}: {v}" for k, v in sorted(by_source.items())) or "  (none)"
    open_ids = summary.get("open_incident_ids") or []
    open_line = ", ".join(open_ids[:8]) if open_ids else "(none)"
    if len(open_ids) > 8:
        open_line += f" … +{len(open_ids) - 8} more"
    return (
        "📅 <b>Today — Incident Summary</b>\n\n"
        f"🔔 <b>Triggered:</b> {summary['triggered']}\n"
        f"🔴 <b>Still failing (events):</b> {summary['still_failing_events']}\n"
        f"🟢 <b>Recovered:</b> {summary['recovered']}\n"
        f"🟡 <b>Suppressed (dedup):</b> {summary['suppressed']}\n\n"
        f"📊 <b>By Source</b>\n{src_lines}\n\n"
        f"📂 <b>Still Open IDs</b>\n<code>{_he(open_line)}</code>"
    )


def _format_status(context: ContextTypes.DEFAULT_TYPE) -> str:
    params = _params(context)
    started = context.bot_data.get("started_at_ist", "unknown")
    last_eod = context.bot_data.get("last_eod_date", "never")
    ledger_exists = read_ledger_rows(limit=1)
    routing = "🟢 Enabled" if params.get("enabled", True) else "🔴 Disabled"
    return (
        "🚨 <b>JAGRAN — Status</b>\n\n"
        f"🕒 <b>Started:</b> <code>{_he(started)}</code>\n"
        f"🔀 <b>Routing:</b> {routing}\n"
        f"⏱️ <b>Dedup window:</b> {params.get('dedup_window_seconds', 300)}s\n"
        f"🔁 <b>Still-failing interval:</b> {params.get('still_failing_interval_seconds', 1800)}s\n"
        f"📅 <b>EOD time (trading days):</b> {params.get('eod_time_ist', '15:32')}\n"
        f"📤 <b>Last EOD sent:</b> <code>{_he(last_eod)}</code>\n"
        f"📂 <b>Open incidents:</b> {active_incident_count()}\n"
        f"🧾 <b>Ledger rows today:</b> {len(ledger_exists)}"
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_alive_menu(_require_message(update))


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_alive_menu(_require_message(update))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _require_message(update).reply_text(
        _format_status(context),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    limit = int(_params(context).get("recent_limit", 10))
    await _require_message(update).reply_text(
        _format_recent_rows(limit=limit),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _require_message(update).reply_text(
        _format_today_summary(),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def _send_test_alert(context: ContextTypes.DEFAULT_TYPE, chat_id: int | str) -> None:
    now = datetime.now(_IST).strftime("%H:%M IST, %d %b %Y")
    await publish_incident(
        source="jagran",
        scenario="test_alert",
        severity="info",
        category="smoke_test",
        title="JAGRAN test alert",
        error_message=f"Smoke test at {now} — routing and delivery OK.",
        next_action="No action required. This is a test.",
        send_to_source=False,
        route_to_jagran=True,
    )


async def cmd_test_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await _send_test_alert(context, message.chat_id)


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _require_query(update)
    await query.answer()
    action = (query.data or "").split(":")[-1]
    if not isinstance(query.message, Message):
        return
    message = query.message
    if action == "status":
        text = _format_status(context)
    elif action == "recent":
        limit = int(_params(context).get("recent_limit", 10))
        text = _format_recent_rows(limit=limit)
    elif action == "today":
        text = _format_today_summary()
    elif action == "test":
        await _send_test_alert(context, message.chat_id)
        await message.reply_text(
            "✅ Test alert sent.",
            reply_markup=_main_menu_keyboard(),
        )
        return
    else:
        text = "Unknown action."
    try:
        await message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
    except BadRequest:
        # Alive card is often a photo — no text body to edit.
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )


async def _unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await _send_alive_menu(update.message)


def _parse_eod_time(params: dict[str, Any]) -> dt_time:
    raw = str(params.get("eod_time_ist", "15:32"))
    parts = raw.split(":")
    hour = int(parts[0]) if parts else 15
    minute = int(parts[1]) if len(parts) > 1 else 30
    return dt_time(hour, minute)


async def _send_eod_digest(app: Application) -> None:
    if not is_trading_day(datetime.now(_IST).date()):
        return
    chat_id = app.bot_data.get("chat_id")
    if not chat_id:
        return
    summary = summarize_day()
    by_source = summary.get("by_source") or {}
    src_lines = "\n".join(f"  {k}: {v}" for k, v in sorted(by_source.items())) or "  (none)"
    open_ids = summary.get("open_incident_ids") or []
    open_line = ", ".join(open_ids) if open_ids else "(none)"
    today = datetime.now(_IST).strftime("%d-%b-%Y")
    text = (
        f"📋 <b>JAGRAN EOD digest — {today}</b>\n\n"
        f"Triggered: <b>{summary['triggered']}</b>\n"
        f"Recovered: <b>{summary['recovered']}</b>\n"
        f"Still open: <b>{len(open_ids)}</b>\n\n"
        f"<b>By source</b>\n{src_lines}\n\n"
        f"<b>Open incident IDs</b>\n<code>{open_line}</code>"
    )
    await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
    app.bot_data["last_eod_date"] = datetime.now(_IST).date().isoformat()
    logger.info("JAGRAN EOD digest sent")


async def _eod_scheduler_loop(app: Application) -> None:
    """Send EOD digest once per trading day at configured IST time."""
    while True:
        try:
            await asyncio.sleep(30)
            now = datetime.now(_IST)
            if not is_trading_day(now.date()):
                continue
            eod = _parse_eod_time(cast(dict[str, Any], app.bot_data.get("params") or {}))
            if now.time() < eod:
                continue
            last = app.bot_data.get("last_eod_date")
            today_key = now.date().isoformat()
            if last == today_key:
                continue
            await _send_eod_digest(app)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("JAGRAN EOD scheduler error: %s", exc)


async def _post_init(application: Application) -> None:
    create_managed_task(
        application,
        "jagran_eod_scheduler",
        _eod_scheduler_loop(application),
        name="jagran_eod_scheduler",
    )
    logger.info("JAGRAN: EOD scheduler started")


async def _on_handler_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Telegram handler failures and return operator to the alive menu."""
    logger.error("JAGRAN handler error: %s", context.error, exc_info=context.error)
    if not isinstance(update, Update):
        return
    message = update.effective_message
    if message is None:
        return
    try:
        await message.reply_text(
            "⚠️ <b>Something went wrong.</b> Tap <b>Status</b> or send /start again.",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
    except Exception:
        pass


def build_application() -> Application:
    cfg = load_bot_config("jagran")
    from core import utils as _u

    app = (
        Application.builder()
        .token(cfg.bot_token)
        .concurrent_updates(True)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(60.0)
        .media_write_timeout(60.0)
        .post_init(_post_init)
        .build()
    )
    app.bot_data["chat_id"] = cfg.chat_id
    app.bot_data["params"] = cfg.params
    app.bot_data["started_at_ist"] = _u.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")

    try:

        from bat_telegram.update_audit import attach_update_audit

        attach_update_audit(app)

    except Exception as _audit_exc:

        logging.getLogger(__name__).warning("update audit attach failed: %s", _audit_exc)

    

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("recent", cmd_recent))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("test_alert", cmd_test_alert))
    app.add_handler(CallbackQueryHandler(cb_menu, pattern=f"^{_CB_MENU}:"))
    app.add_handler(MessageHandler(filters.COMMAND, _unknown))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _unknown))

    app.add_error_handler(_on_handler_error)
    app.post_stop = cleanup_managed_runtime

    return app
