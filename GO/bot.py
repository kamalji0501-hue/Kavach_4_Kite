"""
GO Bot — independent Telegram robot (not Phase 1).

Modes:
  • Multi-leg Batman 2.0 — entry-only 8-leg deploy from NIFTY level
  • Single-leg — Buy CE/PE with fixed SL/Target, trailing, and Exit
"""

from __future__ import annotations

import asyncio
import html
import logging
import zoneinfo
from datetime import datetime
from typing import Any, cast

from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bat_telegram.alive_branding import reply_alive_card
from bat_telegram.loader import load_bot_config
from core.environment_display import environment_label
from GO.book import load_active_book
from GO.strategy import multileg_entry, single_leg
from GO.strategy.batman2_legs import snap_strike
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

logger = logging.getLogger("batman.go")

_CB = "go"
_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_HELP = (
    "<b>GO — Help</b>\n\n"
    "Independent NIFTY options bot (not Phase 1).\n\n"
    "<b>Multi-leg</b> — Deploy Batman 2.0 (8 legs, entry only)\n"
    "<b>Single-leg</b> — Buy CE/PE with SL, Target, trailing + Exit\n\n"
    "/start — Home card\n"
    "/ping — Liveness\n"
    "/status — Mode + broker + book\n"
    "/cancel — Abort wizard"
)

# Conversation states
(
    ML_LEVEL,
    ML_LOTS,
    ML_CONFIRM,
    SL_STRIKE,
    SL_LOTS,
    SL_SL,
    SL_TARGET,
    SL_CONFIRM,
) = range(8)


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


def _lot_size(context: ContextTypes.DEFAULT_TYPE) -> int:
    p = _params(context)
    return int(p.get("lot_size", 65))


def _mode(context: ContextTypes.DEFAULT_TYPE) -> str:
    return str(context.bot_data.get("go_mode") or _params(context).get("default_mode") or "single")


def _set_mode(context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    context.bot_data["go_mode"] = mode


def _broker(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data.get("broker")


def _root(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data.get("workspace_root")


def _main_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """KAVACH-style 2-column grid; GO actions only."""
    mode = _mode(context)
    rows = [
        [
            InlineKeyboardButton(
                f"{'✅' if mode == 'single' else '○'} Single-leg",
                callback_data=f"{_CB}:mode:single",
            ),
            InlineKeyboardButton(
                f"{'✅' if mode == 'multileg' else '○'} Multi-leg",
                callback_data=f"{_CB}:mode:multileg",
            ),
        ],
        [
            InlineKeyboardButton("📊 GO Status", callback_data=f"{_CB}:status"),
            InlineKeyboardButton("📖 Open Book", callback_data=f"{_CB}:book"),
        ],
    ]
    if mode == "single":
        rows.append(
            [
                InlineKeyboardButton("🟢 Buy CE", callback_data=f"{_CB}:buy:CE"),
                InlineKeyboardButton("🔴 Buy PE", callback_data=f"{_CB}:buy:PE"),
            ]
        )
        rows.append([InlineKeyboardButton("🚪 Exit Position", callback_data=f"{_CB}:exit")])
    else:
        rows.append(
            [InlineKeyboardButton("🦇 Deploy Batman 2.0", callback_data=f"{_CB}:deploy")]
        )
    rows.append(
        [
            InlineKeyboardButton("🏠 Home", callback_data=f"{_CB}:home"),
            InlineKeyboardButton("❓ Help", callback_data=f"{_CB}:help"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _alive_caption(context: ContextTypes.DEFAULT_TYPE) -> str:
    now = datetime.now(_IST).strftime("%d-%b-%Y %H:%M:%S IST")
    mode_label = (
        environment_label().replace("(virtual)", "(Virtual)").replace("(live)", "(Live)")
    )
    go_mode = _mode(context)
    go_mode_label = "Single-leg" if go_mode == "single" else "Multi-leg (Batman 2.0)"
    broker = "Connected" if _broker(context) else "None (JWT)"
    book = load_active_book(_root(context))
    if book:
        book_line = f"{book.get('mode')} · {book.get('status')} ({book.get('id')})"
    else:
        book_line = "No open book"
    return (
        f"🟢 <b>GO ACTIVE</b>\n"
        f"Mode: <b>{_he(mode_label)}</b>\n"
        f"Trade: <b>{_he(go_mode_label)}</b>\n"
        f"<code>{now}</code>\n"
        f"Broker: <b>{_he(broker)}</b>\n"
        f"Book: <b>{_he(book_line)}</b>"
    )


async def _send_alive_menu(message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logo on top + status caption + GO menu (same pattern as KAVACH 2.0)."""
    await reply_alive_card(
        message,
        _alive_caption(context),
        reply_markup=_main_menu(context),
        bot_name="go",
    )


async def _reply_with_menu(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    with_menu: bool = True,
) -> None:
    """Reply under the photo card (edit_message_text fails on photo messages)."""
    if query.message is None:
        return
    markup = reply_markup if reply_markup is not None else (_main_menu(context) if with_menu else None)
    await query.message.reply_html(text, reply_markup=markup)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_alive_menu(_require_message(update), context)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await message.reply_text("GO pong ✓")
    await _send_alive_menu(message, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await message.reply_html(_status_html(context), reply_markup=_main_menu(context))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    message = _require_message(update)
    await message.reply_text("Wizard cancelled.")
    await _send_alive_menu(message, context)
    return ConversationHandler.END


def _status_html(context: ContextTypes.DEFAULT_TYPE) -> str:
    broker = _broker(context)
    book = load_active_book(_root(context))
    broker_line = "connected" if broker else "none (refresh JWT via DRISHTI)"
    book_line = "none"
    if book:
        book_line = f"{book.get('mode')} / {book.get('status')} / {book.get('id')}"
    return (
        f"<b>📊 GO Status</b>\n\n"
        f"Trade mode: <code>{_he(_mode(context))}</code>\n"
        f"Env: <code>{_he(environment_label())}</code>\n"
        f"Broker: {_he(broker_line)}\n"
        f"Book: {_he(book_line)}\n"
        f"Scope: independent (not Phase 1)"
    )


def _book_html(book: dict[str, Any] | None) -> str:
    if not book:
        return "No active GO book."
    lines = [
        f"<b>GO Book</b> <code>{_he(book.get('id'))}</code>",
        f"Mode: {_he(book.get('mode'))} | Status: {_he(book.get('status'))}",
    ]
    if book.get("mode") == "multileg":
        lines.append(f"Center: {_he(book.get('center_level'))} | Expiry: {_he(book.get('expiry'))}")
        for leg in book.get("legs") or []:
            lines.append(
                f"• {_he(leg.get('key'))} {_he(leg.get('side'))} "
                f"{_he(leg.get('symbol') or leg.get('strike'))} "
                f"×{_he(leg.get('qty'))} [{_he(leg.get('status'))}]"
            )
    else:
        lines.append(
            f"{_he(book.get('option_type'))} {_he(book.get('symbol'))} ×{_he(book.get('qty'))}"
        )
        lines.append(
            f"Entry≈{_he(book.get('entry_premium'))} "
            f"SL={_he(book.get('sl_price'))} TGT={_he(book.get('target_price'))}"
        )
        if book.get("trail_active"):
            lines.append(
                f"Trail SL={_he(book.get('trail_sl'))} TGT={_he(book.get('trail_target'))}"
            )
        if book.get("exit_reason"):
            lines.append(f"Exit: {_he(book.get('exit_reason'))}")
    return "\n".join(lines)


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    query = _require_query(update)
    await query.answer()
    data = str(query.data or "")
    parts = data.split(":")
    if len(parts) < 2 or parts[0] != _CB:
        return None

    action = parts[1]

    if action == "home":
        if query.message is not None:
            await _send_alive_menu(query.message, context)
        return None

    if action == "mode" and len(parts) >= 3:
        _set_mode(context, parts[2])
        if query.message is not None:
            await _send_alive_menu(query.message, context)
        return None

    if action == "status":
        await _reply_with_menu(query, context, _status_html(context))
        return None

    if action == "book":
        book = load_active_book(_root(context))
        await _reply_with_menu(query, context, _book_html(book))
        return None

    if action == "help":
        await _reply_with_menu(query, context, _HELP)
        return None

    if action == "exit":
        return await _do_manual_exit(query, context)

    if action == "deploy":
        await _reply_with_menu(
            query,
            context,
            "Send <b>NIFTY center level</b> (e.g. <code>25000</code>).\n"
            "➡️ Type the level now (or /cancel).",
            with_menu=False,
        )
        return ML_LEVEL

    if action == "buy" and len(parts) >= 3:
        context.user_data["sl_side"] = parts[2].upper()
        await _reply_with_menu(
            query,
            context,
            f"Buy <b>{_he(parts[2])}</b> — send strike (or <code>ATM</code>).\n"
            "➡️ Type strike or ATM (or /cancel).",
            with_menu=False,
        )
        return SL_STRIKE

    return None


async def _do_manual_exit(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    broker = _broker(context)
    book = load_active_book(_root(context))
    if not broker:
        await _reply_with_menu(query, context, "No broker — update JWT via DRISHTI first.")
        return
    if not book or book.get("mode") != "single" or book.get("status") != "open":
        await _reply_with_menu(query, context, "No open single-leg book to exit.")
        return

    loop = asyncio.get_running_loop()

    def _notify(msg: str) -> None:
        asyncio.run_coroutine_threadsafe(
            context.bot.send_message(chat_id=context.bot_data.get("chat_id"), text=msg),
            loop,
        )

    try:
        await loop.run_in_executor(
            None,
            lambda: single_leg.exit_single_leg(
                broker,
                book,
                reason="operator_exit",
                params=_params(context),
                root=_root(context),
                notify=_notify,
            ),
        )
        await _reply_with_menu(query, context, "✅ Exit submitted.")
        if query.message is not None:
            await _send_alive_menu(query.message, context)
    except Exception as exc:
        await _reply_with_menu(query, context, f"Exit failed: {_he(exc)}")


# ── Multi-leg wizard ──────────────────────────────────────────────────────────


async def ml_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = _require_message(update)
    text = (message.text or "").strip().replace(",", "")
    try:
        level = float(text)
    except ValueError:
        await message.reply_text("Send a number for NIFTY level (e.g. 25000).")
        return ML_LEVEL
    context.user_data["ml_level"] = level
    default_lots = int(_params(context).get("base_lots", 1))
    await message.reply_text(f"Base lots? (default {default_lots})")
    return ML_LOTS


async def ml_lots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = _require_message(update)
    text = (message.text or "").strip()
    default_lots = int(_params(context).get("base_lots", 1))
    try:
        lots = int(text) if text else default_lots
    except ValueError:
        await message.reply_text("Send an integer lots count.")
        return ML_LOTS
    if lots < 1:
        await message.reply_text("Lots must be >= 1.")
        return ML_LOTS

    level = float(context.user_data["ml_level"])
    lot_size = _lot_size(context)
    legs, preview = multileg_entry.build_preview(
        level, base_lots=lots, lot_size=lot_size, params=_params(context)
    )
    exp = multileg_entry.resolve_expiry()
    from core.nifty_option_expiry import expiry_label_from_date

    exp_label = expiry_label_from_date(exp)
    context.user_data["ml_lots"] = lots
    context.user_data["ml_expiry"] = exp.isoformat()
    text_preview = multileg_entry.format_preview_text(
        level, preview, expiry_label=exp_label, base_lots=lots
    )
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"{_CB}:ml_yes"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB}:ml_no"),
            ]
        ]
    )
    await message.reply_text(f"<pre>{_he(text_preview)}</pre>", parse_mode=ParseMode.HTML, reply_markup=kb)
    return ML_CONFIRM


async def ml_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    await query.answer()
    if str(query.data).endswith(":ml_no"):
        await query.edit_message_text("Deploy cancelled.")
        if query.message is not None:
            await _send_alive_menu(query.message, context)
        context.user_data.clear()
        return ConversationHandler.END

    broker = _broker(context)
    if not broker:
        await query.edit_message_text("No broker — update JWT in DRISHTI first.")
        return ConversationHandler.END

    level = float(context.user_data["ml_level"])
    lots = int(context.user_data["ml_lots"])
    expiry = context.user_data.get("ml_expiry")
    await query.edit_message_text("Deploying Batman 2.0… (this may take a minute)")

    loop = asyncio.get_running_loop()
    chat_id = context.bot_data.get("chat_id")

    def _notify(msg: str) -> None:
        if chat_id:
            asyncio.run_coroutine_threadsafe(
                context.bot.send_message(chat_id=chat_id, text=msg), loop
            )

    try:
        book = await loop.run_in_executor(
            None,
            lambda: multileg_entry.deploy_multileg(
                broker,
                center_level=level,
                base_lots=lots,
                lot_size=_lot_size(context),
                expiry=expiry,
                params=_params(context),
                root=_root(context),
                notify=_notify,
            ),
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id if update.effective_chat else chat_id,
            text=_book_html(book),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu(context),
        )
    except Exception as exc:
        await context.bot.send_message(
            chat_id=update.effective_chat.id if update.effective_chat else chat_id,
            text=f"Deploy failed: {_he(exc)}",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu(context),
        )
    context.user_data.clear()
    return ConversationHandler.END


# ── Single-leg wizard ─────────────────────────────────────────────────────────


async def sl_strike(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = _require_message(update)
    text = (message.text or "").strip().upper()
    step = int(_params(context).get("strike_step", 50))
    if text in {"ATM", "A"}:
        broker = _broker(context)
        if not broker:
            await message.reply_text("No broker for ATM — send a numeric strike.")
            return SL_STRIKE
        try:
            spot = float(broker.get_nifty_ltp())
            strike = snap_strike(spot, step)
        except Exception as exc:
            await message.reply_text(f"ATM failed: {exc}. Send a numeric strike.")
            return SL_STRIKE
    else:
        try:
            strike = snap_strike(float(text.replace(",", "")), step)
        except ValueError:
            await message.reply_text("Send strike number or ATM.")
            return SL_STRIKE
    context.user_data["sl_strike"] = strike
    default_lots = int(_params(context).get("base_lots", 1))
    await message.reply_text(f"Lots? (default {default_lots})")
    return SL_LOTS


async def sl_lots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = _require_message(update)
    text = (message.text or "").strip()
    default_lots = int(_params(context).get("base_lots", 1))
    try:
        lots = int(text) if text else default_lots
    except ValueError:
        await message.reply_text("Send integer lots.")
        return SL_LOTS
    if lots < 1:
        await message.reply_text("Lots must be >= 1.")
        return SL_LOTS
    context.user_data["sl_lots"] = lots
    default_sl = _params(context).get("default_sl_rupees", 10)
    await message.reply_text(
        f"Fixed SL in premium points? (default {default_sl} points)"
    )
    return SL_SL


async def sl_sl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = _require_message(update)
    text = (message.text or "").strip()
    default_sl = float(_params(context).get("default_sl_rupees", 10))
    try:
        sl = float(text) if text else default_sl
    except ValueError:
        await message.reply_text("Send SL as a number (premium points).")
        return SL_SL
    context.user_data["sl_rupees"] = abs(sl)
    default_tgt = _params(context).get("default_target_rupees", 20)
    await message.reply_text(
        f"Fixed Target in premium points? (default {default_tgt} points)"
    )
    return SL_TARGET


async def sl_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = _require_message(update)
    text = (message.text or "").strip()
    default_tgt = float(_params(context).get("default_target_rupees", 20))
    try:
        tgt = float(text) if text else default_tgt
    except ValueError:
        await message.reply_text("Send Target as a number (premium points).")
        return SL_TARGET
    context.user_data["sl_target"] = abs(tgt)

    side = context.user_data.get("sl_side", "CE")
    strike = context.user_data["sl_strike"]
    lots = context.user_data["sl_lots"]
    sl = context.user_data["sl_rupees"]
    summary = (
        f"Buy {side} {strike} × {lots} lot(s)\n"
        f"SL −{sl:.2f} pts | Target +{tgt:.2f} pts\n"
        f"Confirm?"
    )
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"{_CB}:sl_yes"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB}:sl_no"),
            ]
        ]
    )
    await message.reply_text(summary, reply_markup=kb)
    return SL_CONFIRM


async def sl_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    await query.answer()
    if str(query.data).endswith(":sl_no"):
        await query.edit_message_text("Entry cancelled.")
        if query.message is not None:
            await _send_alive_menu(query.message, context)
        context.user_data.clear()
        return ConversationHandler.END

    broker = _broker(context)
    if not broker:
        await query.edit_message_text("No broker — update JWT in DRISHTI first.")
        return ConversationHandler.END

    await query.edit_message_text("Placing single-leg BUY…")
    loop = asyncio.get_running_loop()
    chat_id = context.bot_data.get("chat_id")

    def _notify(msg: str) -> None:
        if chat_id:
            asyncio.run_coroutine_threadsafe(
                context.bot.send_message(chat_id=chat_id, text=msg), loop
            )

    try:
        book = await loop.run_in_executor(
            None,
            lambda: single_leg.enter_single_leg(
                broker,
                option_type=str(context.user_data.get("sl_side", "CE")),
                strike=int(context.user_data["sl_strike"]),
                lots=int(context.user_data["sl_lots"]),
                lot_size=_lot_size(context),
                sl_rupees=float(context.user_data["sl_rupees"]),
                target_rupees=float(context.user_data["sl_target"]),
                params=_params(context),
                root=_root(context),
                notify=_notify,
            ),
        )
        # Ensure monitor is running
        monitor = context.bot_data.get("single_leg_monitor")
        if monitor:
            monitor.start()
        await context.bot.send_message(
            chat_id=update.effective_chat.id if update.effective_chat else chat_id,
            text=_book_html(book),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu(context),
        )
    except Exception as exc:
        await context.bot.send_message(
            chat_id=update.effective_chat.id if update.effective_chat else chat_id,
            text=f"Entry failed: {_he(exc)}",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu(context),
        )
    context.user_data.clear()
    return ConversationHandler.END


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await _send_alive_menu(message, context)


async def _on_handler_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("GO handler error: %s", context.error, exc_info=context.error)


def build_application(
    broker=None,
    *,
    workspace_root=None,
    single_leg_monitor=None,
) -> Application:
    cfg = load_bot_config("go")
    from core import utils as _u

    app = (
        Application.builder()
        .token(cfg.bot_token)
        .concurrent_updates(True)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(60.0)
        .media_write_timeout(60.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(60.0)
        .get_updates_write_timeout(30.0)
        .build()
    )
    app.bot_data["chat_id"] = cfg.chat_id
    app.bot_data["params"] = cfg.params
    app.bot_data["broker"] = broker
    app.bot_data["workspace_root"] = workspace_root
    app.bot_data["single_leg_monitor"] = single_leg_monitor
    app.bot_data["go_mode"] = str(cfg.params.get("default_mode") or "single")
    app.bot_data["started_at_ist"] = _u.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_menu, pattern=f"^{_CB}:(deploy|buy:)")],
        states={
            ML_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ml_level)],
            ML_LOTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ml_lots)],
            ML_CONFIRM: [CallbackQueryHandler(ml_confirm_cb, pattern=f"^{_CB}:ml_")],
            SL_STRIKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sl_strike)],
            SL_LOTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, sl_lots)],
            SL_SL: [MessageHandler(filters.TEXT & ~filters.COMMAND, sl_sl)],
            SL_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, sl_target)],
            SL_CONFIRM: [CallbackQueryHandler(sl_confirm_cb, pattern=f"^{_CB}:sl_")],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
        ],
        allow_reentry=True,
        name="go_wizards",
        persistent=False,
        per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(conv)
    # Non-wizard menu callbacks (mode/status/book/help/exit)
    app.add_handler(
        CallbackQueryHandler(cb_menu, pattern=f"^{_CB}:(mode|status|book|help|exit|home)")
    )
    app.add_handler(MessageHandler(filters.COMMAND, on_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(_on_handler_error)

    logger.info("GO bot application built ✓")
    return app
