#!/usr/bin/env python3
"""
Capture the latest chat that messaged DRISHTI and save DRISHTI_CHAT_ID.

Before running this script:
1. Open Telegram.
2. Search for your DRISHTI bot.
3. Send /start to the bot.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from telegram.error import Conflict

from bat_telegram.loader import load_bot_config
from telegram import Bot

TOKEN_FILE = Path(__file__).parent / "telegram" / "bots" / "drishti" / "token.env"


def _replace_chat_id(chat_id: int) -> None:
    text = TOKEN_FILE.read_text(encoding="utf-8")
    replacement = f"DRISHTI_CHAT_ID={chat_id}"
    if re.search(r"^DRISHTI_CHAT_ID=.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^DRISHTI_CHAT_ID=.*$", replacement, text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + "\n" + replacement + "\n"
    TOKEN_FILE.write_text(text, encoding="utf-8")


async def main() -> None:
    cfg = load_bot_config("drishti", reload_token=True, reload_params=True)
    bot = Bot(cfg.bot_token)

    try:
        updates = await bot.get_updates(limit=20, timeout=5)
    except Conflict:
        print("Another DRISHTI bot polling session is already running.")
        print("Stop run_drishti.py/main.py first, then run this setup helper again.")
        return
    chats = []
    seen = set()
    for update in reversed(updates):
        chat = update.effective_chat
        if chat is None or chat.id in seen:
            continue
        seen.add(chat.id)
        chats.append(chat)

    if not chats:
        print("No Telegram chat found yet.")
        print("Send /start to your DRISHTI bot in Telegram, then run this script again.")
        return

    chat = chats[0]
    _replace_chat_id(chat.id)
    title = chat.title or chat.full_name or chat.username or str(chat.id)
    print(f"Saved DRISHTI_CHAT_ID={chat.id}")
    print(f"Chat: {title} ({chat.type})")


if __name__ == "__main__":
    asyncio.run(main())
