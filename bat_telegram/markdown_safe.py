"""Shared Telegram MarkdownV2 safe send helpers."""

from __future__ import annotations

import logging
from typing import Any

from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.helpers import escape_markdown

from telegram import InlineKeyboardMarkup, Message

logger = logging.getLogger("batman.telegram_safe")


def md2_escape(text: str) -> str:
    return escape_markdown(str(text), version=2)


def md2_code(text: str) -> str:
    return escape_markdown(str(text), version=2, entity_type="code")


async def reply_md2_safe(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    bot_label: str = "bot",
) -> None:
    """Send MarkdownV2; fall back to plain text if Telegram rejects entities."""
    kwargs: dict[str, Any] = {"parse_mode": ParseMode.MARKDOWN_V2}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    try:
        await message.reply_text(text, **kwargs)
    except BadRequest as exc:
        msg = str(exc).lower()
        if "parse entities" not in msg and "can't parse" not in msg:
            raise
        logger.warning("%s MarkdownV2 rejected — plain fallback: %s", bot_label, exc)
        plain = text.replace("\\", "").replace("*", "").replace("_", "").replace("`", "")
        await message.reply_text(plain, reply_markup=reply_markup)


async def edit_md2_safe(
    query_message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    bot_label: str = "bot",
) -> None:
    kwargs: dict[str, Any] = {"parse_mode": ParseMode.MARKDOWN_V2}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    try:
        await query_message.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        msg = str(exc).lower()
        if "parse entities" not in msg and "can't parse" not in msg:
            raise
        logger.warning("%s edit MarkdownV2 rejected — plain fallback: %s", bot_label, exc)
        plain = text.replace("\\", "").replace("*", "").replace("_", "").replace("`", "")
        await query_message.edit_message_text(plain, reply_markup=reply_markup)
