"""Telegram notifier — credentials from .env only."""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from telegram import Bot

ENV_PATH = os.getenv("TELEGRAM_ENV_PATH", "/home/ubuntu/my_telegram_bot/.env")
load_dotenv(ENV_PATH)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


async def _send_async(message: str) -> bool:
    if not TOKEN or not CHAT_ID:
        return False
    bot = Bot(token=TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=message)
    return True


def notify(message: str) -> bool:
    try:
        return asyncio.run(_send_async(message))
    except Exception:
        return False
