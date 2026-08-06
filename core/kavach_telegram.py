"""Send operator messages to the KAVACH Telegram chat (from DRISHTI watchdog)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from telegram import Bot
from telegram.constants import ParseMode

from core.telegram_delivery import send_with_retry

logger = logging.getLogger("batman.kavach_telegram")

_ROOT = Path(__file__).resolve().parent.parent
_KAVACH_TOKEN_ENV = _ROOT / "telegram" / "bots" / "kavach" / "token.env"


def _load_kavach_credentials() -> tuple[str | None, str | None]:
    """Prefer desktop bots.env; fall back to legacy repo token.env."""
    try:
        from core.telegram_credentials import get_bot_credentials, is_placeholder

        token, chat_id, _src = get_bot_credentials("kavach")
        if token and not is_placeholder(token) and chat_id and not is_placeholder(chat_id):
            return token, chat_id
    except Exception:
        pass
    if not _KAVACH_TOKEN_ENV.exists():
        return None, None
    text = _KAVACH_TOKEN_ENV.read_text(encoding="utf-8")
    token_m = re.search(r"^KAVACH_BOT_TOKEN=(.+)$", text, re.MULTILINE)
    chat_m = re.search(r"^KAVACH_CHAT_ID=(.+)$", text, re.MULTILINE)
    token = token_m.group(1).strip() if token_m else None
    chat_id = chat_m.group(1).strip() if chat_m else None
    return token, chat_id



async def send_kavach_html(
    text: str,
    *,
    reply_markup=None,
) -> bool:
    token, chat_id = _load_kavach_credentials()
    if not token or not chat_id:
        logger.debug("KAVACH notify skipped — missing token or chat id")
        return False
    try:
        bot = Bot(token=token)
        return await send_with_retry(
            bot.send_message,
            chat_id=int(chat_id),
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            log_prefix="KAVACH notify",
        )
    except Exception as exc:
        logger.warning("KAVACH notify failed: %s", exc)
        return False
