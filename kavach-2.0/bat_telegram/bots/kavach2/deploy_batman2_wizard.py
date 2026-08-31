"""KAVACH 2.0 — Deploy Batman 2.0 wizard (NIFTY level → lots → confirm → place)."""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Any, cast

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update


def _btn(text: str, callback_data: str, *, style: str | None = None) -> InlineKeyboardButton:
    """Inline button with optional Telegram style: primary|success|danger."""
    kwargs: dict[str, Any] = {"text": text, "callback_data": callback_data}
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)

from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bat_telegram.bots.kavach2.strategy import multileg_entry

logger = logging.getLogger("batman.kavach2.deploy_batman2")

WIZARD_CONVERSATION_NAME = "kavach2_deploy_batman2"

(
    B2_LEVEL,
    B2_LOTS,
    B2_CONFIRM,
) = range(3)

_CB_B2 = "kav2_b2"
_USER_KEYS = ("b2_level", "b2_lots", "b2_expiry")


def _bot():
    import bat_telegram.bots.kavach2.bot as bot_mod

    return bot_mod


def _ud(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return cast(dict[str, Any], context.user_data)


def _clear_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    ud = _ud(context)
    for key in _USER_KEYS:
        ud.pop(key, None)


def _he(text: Any) -> str:
    return html.escape(str(text), quote=False)


def _deploy_params(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    params = cast(dict[str, Any], context.bot_data.get("params") or {})
    section = params.get("batman2_deploy")
    return dict(section) if isinstance(section, dict) else {}


def _lot_size(context: ContextTypes.DEFAULT_TYPE) -> int:
    params = cast(dict[str, Any], context.bot_data.get("params") or {})
    strategy = params.get("strategy") if isinstance(params.get("strategy"), dict) else {}
    return int(strategy.get("lot_size", 65))


async def deploy_entry_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry from main-menu button."""
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    message = query.message
    if message is None:
        return ConversationHandler.END
    _clear_data(context)
    await message.reply_html(
        "Send <b>NIFTY center level</b> (e.g. <code>25000</code>).\n"
        "➡️ Type the level now (or /cancel).",
    )
    return B2_LEVEL


async def b2_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    text = (message.text or "").strip().replace(",", "")
    try:
        level = float(text)
    except ValueError:
        await message.reply_text("Send a number for NIFTY level (e.g. 25000).")
        return B2_LEVEL
    _ud(context)["b2_level"] = level
    default_lots = int(_deploy_params(context).get("base_lots", 1))
    await message.reply_text(f"Base lots? (default {default_lots})")
    return B2_LOTS


async def b2_lots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    text = (message.text or "").strip()
    default_lots = int(_deploy_params(context).get("base_lots", 1))
    try:
        lots = int(text) if text else default_lots
    except ValueError:
        await message.reply_text("Send an integer lots count.")
        return B2_LOTS
    if lots < 1:
        await message.reply_text("Lots must be >= 1.")
        return B2_LOTS

    level = float(_ud(context)["b2_level"])
    lot_size = _lot_size(context)
    params = _deploy_params(context)
    _, preview = multileg_entry.build_preview(
        level, base_lots=lots, lot_size=lot_size, params=params
    )
    exp = multileg_entry.resolve_expiry()
    from core.nifty_option_expiry import expiry_label_from_date

    exp_label = expiry_label_from_date(exp)
    _ud(context)["b2_lots"] = lots
    _ud(context)["b2_expiry"] = exp.isoformat()
    text_preview = multileg_entry.format_preview_text(
        level, preview, expiry_label=exp_label, base_lots=lots
    )
    kb = InlineKeyboardMarkup(
        [
            [
                _btn("✅ Confirm", f"{_CB_B2}:yes", style="success"),
                _btn("❌ Cancel", f"{_CB_B2}:no", style="danger"),
            ]
        ]
    )
    await message.reply_text(
        f"<pre>{_he(text_preview)}</pre>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return B2_CONFIRM


async def b2_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    data = str(query.data or "")

    if data.endswith(":no"):
        await query.edit_message_text("Deploy cancelled.")
        if query.message is not None:
            await b._send_alive_menu(query.message)
        _clear_data(context)
        return ConversationHandler.END

    broker = context.bot_data.get("broker")
    if not broker:
        await query.edit_message_text("No broker — update JWT via Kavach TOKEN menu first.")
        _clear_data(context)
        return ConversationHandler.END

    level = float(_ud(context)["b2_level"])
    lots = int(_ud(context)["b2_lots"])
    expiry = _ud(context).get("b2_expiry")
    await query.edit_message_text("Deploying Batman 2.0… (this may take a minute)")

    loop = asyncio.get_running_loop()
    chat_id = context.bot_data.get("chat_id")

    def _notify(msg: str) -> None:
        if chat_id:
            asyncio.run_coroutine_threadsafe(
                context.bot.send_message(chat_id=chat_id, text=msg), loop
            )

    try:
        result = await loop.run_in_executor(
            None,
            lambda: multileg_entry.deploy_multileg(
                broker,
                center_level=level,
                base_lots=lots,
                lot_size=_lot_size(context),
                expiry=expiry,
                params=_deploy_params(context),
                notify=_notify,
            ),
        )
        body = multileg_entry.format_result_text(result)
        await context.bot.send_message(
            chat_id=update.effective_chat.id if update.effective_chat else chat_id,
            text=f"<pre>{_he(body)}</pre>",
            parse_mode=ParseMode.HTML,
            reply_markup=b._main_menu_keyboard(),
        )
    except Exception as exc:
        logger.exception("Batman 2.0 deploy failed")
        await context.bot.send_message(
            chat_id=update.effective_chat.id if update.effective_chat else chat_id,
            text=f"Deploy failed: {_he(exc)}",
            parse_mode=ParseMode.HTML,
            reply_markup=b._main_menu_keyboard(),
        )
    _clear_data(context)
    return ConversationHandler.END


async def b2_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    _clear_data(context)
    message = b._require_message(update)
    await message.reply_text("Deploy cancelled.")
    await b._send_alive_menu(message)
    return ConversationHandler.END


async def b2_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    del update
    _clear_data(context)
    logger.info("Batman 2.0 deploy wizard timed out")
    return ConversationHandler.END


def build_deploy_batman2_handler(timeout: int) -> ConversationHandler:
    b = _bot()
    return ConversationHandler(
        allow_reentry=True,
        name=WIZARD_CONVERSATION_NAME,
        entry_points=[
            CallbackQueryHandler(
                deploy_entry_menu, pattern=f"^{b._CB_MENU}:deploy_batman2$"
            ),
        ],
        states={
            B2_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, b2_level)],
            B2_LOTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, b2_lots)],
            B2_CONFIRM: [CallbackQueryHandler(b2_confirm, pattern=f"^{_CB_B2}:")],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, b2_timeout)],
        },
        fallbacks=[
            CommandHandler("cancel", b2_cancel_command),
            CallbackQueryHandler(
                deploy_entry_menu, pattern=f"^{b._CB_MENU}:deploy_batman2$"
            ),
        ],
        conversation_timeout=timeout,
    )


__all__ = [
    "B2_LEVEL",
    "B2_LOTS",
    "B2_CONFIRM",
    "WIZARD_CONVERSATION_NAME",
    "build_deploy_batman2_handler",
    "deploy_entry_menu",
]
