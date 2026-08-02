"""
Batman v3 — Telegram authorization decorator.

Kept in a dedicated module to avoid circular imports between
``bot_manager`` (which registers handlers) and the handler
modules (which need this decorator).
"""

from __future__ import annotations

import functools
import logging

from telegram.ext import ContextTypes

from telegram import Update

logger = logging.getLogger("batman.telegram.auth")


def authorized_only(func):
    """Restrict a Telegram handler to the configured chat_id.

    Any message from an unrecognized sender is rejected with a short
    warning — no strategy information is leaked.

    Usage::

        @authorized_only
        async def _cmd_status(update, context):
            ...
    """

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        authorized_id = str(context.bot_data.get("chat_id", ""))
        user_chat_id = str(update.effective_chat.id) if update.effective_chat else ""

        if not authorized_id or user_chat_id != authorized_id:
            logger.warning(
                "Unauthorized access attempt from chat_id=%s (expected %s)",
                user_chat_id,
                authorized_id,
            )
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ Unauthorized. This bot is restricted."
                )
            return
        return await func(update, context)

    return wrapper
