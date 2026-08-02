#!/usr/bin/env python3
"""Send DRISHTI alive card + menu to configured chat."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _ReplyProxy:
    def __init__(self, bot, chat_id: str):
        self._bot = bot
        self._chat_id = chat_id

    async def reply_text(self, *args, **kwargs):
        return await self._bot.send_message(chat_id=self._chat_id, *args, **kwargs)


async def main() -> None:
    from bat_telegram.loader import load_bot_config
    from telegram import Bot

    cfg = load_bot_config("drishti", reload_token=True)
    bot = Bot(cfg.bot_token)
    import html
    import zoneinfo
    from datetime import datetime

    from bat_telegram.bots.drishti.bot import _main_menu_keyboard

    now = datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).strftime("%d-%b-%Y %H:%M:%S IST")
    msg = await bot.send_message(
        chat_id=cfg.chat_id,
        text=f"🟢 <b>DRISHTI alive</b>\n<code>{html.escape(now)}</code>",
        parse_mode="HTML",
        reply_markup=_main_menu_keyboard(),
    )
    print(f"Sent alive menu (message_id={msg.message_id})")


if __name__ == "__main__":
    asyncio.run(main())
