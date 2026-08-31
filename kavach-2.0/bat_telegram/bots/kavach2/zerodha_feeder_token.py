"""Kavach Telegram delivery of the Feeder Zerodha access_token.

Writes Kavach shared + Datafeedbot runtime files. Never used for Kavach orders.
"""

from __future__ import annotations

import html
import logging
import os
from pathlib import Path
from typing import Any

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core.token_fanout import (
    feeder_zerodha_env_path,
    feeder_zerodha_json_path,
    kavach_zerodha_json_path,
    persist_zerodha_token,
)

logger = logging.getLogger("batman.kavach2.zerodha")

AWAITING_ZERODHA_TOKEN_KEY = "awaiting_kavach_zerodha_token"


def set_awaiting_zerodha_token(context: ContextTypes.DEFAULT_TYPE | None, value: bool) -> None:
    if context is not None:
        context.user_data[AWAITING_ZERODHA_TOKEN_KEY] = value


def is_awaiting_zerodha_token(context: ContextTypes.DEFAULT_TYPE | None) -> bool:
    if context is None:
        return False
    return bool(context.user_data.get(AWAITING_ZERODHA_TOKEN_KEY, False))


def looks_like_kite_access_token(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 20:
        return False
    if t.startswith("/") or " " in t or "\n" in t:
        return False
    if t.startswith("http://") or t.startswith("https://"):
        return False
    if "request_token=" in t:
        return False
    return True


def _last4(token: str) -> str:
    t = (token or "").strip()
    if len(t) < 4:
        return "----"
    return t[-4:]


def _read_json_status(path: Path) -> tuple[str, str]:
    import json
    from datetime import datetime

    if not path.is_file():
        return "", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return "", ""
        tok = str(data.get("access_token") or data.get("token") or "").strip()
        saved = str(data.get("saved_at") or "").strip()
        return tok, saved
    except Exception:
        return "", ""


def status_html() -> str:
    from datetime import datetime
    import zoneinfo

    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    best_tok = ""
    best_saved = ""
    best_mtime = -1.0
    for p in (feeder_zerodha_json_path(), kavach_zerodha_json_path()):
        tok, saved = _read_json_status(p)
        if not tok:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime >= best_mtime:
            best_mtime = mtime
            best_tok = tok
            best_saved = saved
    if not best_tok:
        return (
            "📡 <b>Feeder Zerodha</b>\n"
            "Not set — tap <b>SET FEEDER ZERODHA TOKEN</b> and paste the Kite access_token."
        )
    disp = best_saved
    try:
        dt = datetime.fromisoformat(best_saved)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ist)
        disp = dt.astimezone(ist).strftime("%d-%b %H:%M IST")
    except Exception:
        if not disp:
            disp = "unknown"
    return (
        "📡 <b>Feeder Zerodha</b>\n"
        f"Set · saved {html.escape(disp)} · last4 ····{html.escape(_last4(best_tok))}"
    )


def _api_key_from_env() -> str:
    env_path = feeder_zerodha_env_path()
    if not env_path.is_file():
        return os.environ.get("ZERODHA_API_KEY", "").strip()
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "ZERODHA_API_KEY":
                return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get("ZERODHA_API_KEY", "").strip()


def validate_kite_token(access_token: str) -> tuple[bool, str]:
    api_key = _api_key_from_env()
    if not api_key:
        return True, "no_api_key_skip"
    try:
        from datafeedbot.auth.zerodha_token import validate_access_token

        profile = validate_access_token(api_key, access_token)
    except Exception as exc:
        logger.warning("Kite profile check failed: %s", exc)
        return False, "kite_profile_error"
    if not profile:
        return False, "kite_rejected"
    uid = str(profile.get("user_id") or "").strip()
    return True, uid or "ok"


async def process_pasted_zerodha_token(
    update: Update,
    token: str,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    reply_markup: Any = None,
) -> None:
    set_awaiting_zerodha_token(context, False)
    if update.message is None:
        raise ValueError("Telegram update is missing a message")
    message: Message = update.message
    raw = (token or "").strip()

    try:
        await message.delete()
    except Exception:
        logger.debug("Could not delete Zerodha token Telegram message")

    async def _reply(text: str) -> None:
        await message.chat.send_message(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )

    if "." in raw and raw.count(".") >= 2:
        await _reply(
            "🔴 <b>That looks like a Dhan JWT</b>\n\n"
            "This button is for the <b>Kite access_token</b> (Feeder only).\n"
            "For Dhan, use <b>PASTE DHAN JWT</b> or <b>REFRESH JWT</b>."
        )
        return

    try:
        from core.zerodha_token_exchange import resolve_kite_access_token

        access, detail = resolve_kite_access_token(raw)
    except ValueError as exc:
        await _reply(
            "🔴 <b>Could not use that Kite token</b>\n\n"
            f"<code>{html.escape(str(exc))}</code>\n\n"
            "Paste the full login redirect URL (with <code>request_token=</code>) "
            "right after Kite login, or a fresh access_token."
        )
        return

    ok, reason = validate_kite_token(access)
    if not ok:
        await _reply(
            "🔴 <b>Kite rejected the token</b>\n\n"
            "Nothing was saved. Paste a fresh Kite login URL or access_token."
        )
        return

    try:
        root = context.bot_data.get("workspace_root")
        saved_at = persist_zerodha_token(
            access,
            root=root,
            source="kavach2_telegram",
            user_id=str(detail) if detail not in ("ok", "") else "",
        )
    except Exception as exc:
        logger.error("Feeder Zerodha token persist failed: %s", exc)
        await _reply(
            "🔴 <b>Could not save feeder Zerodha token</b>\n\n"
            f"<code>{html.escape(str(exc))}</code>"
        )
        return

    saved_fmt = saved_at.strftime("%d-%b %H:%M")
    extra = ""
    if reason not in ("ok", "no_api_key_skip") and reason:
        extra = f"\nKite user: <code>{html.escape(reason)}</code>"
    await _reply(
        "✅ <b>Zerodha token saved for Kavach and Feeder</b>\n\n"
        f"Last4: ····{html.escape(_last4(access))}\n"
        f"Saved: {html.escape(saved_fmt)}\n"
        "Feeder will use this for Zerodha data. Kavach orders also go to Zerodha."
        f"{extra}"
    )
