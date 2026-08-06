"""Telegram Update audit — log every inbound update (commands, callbacks, text).

Attach once per Application via ``attach_update_audit(app)``. Uses group=-1 so
it runs before business handlers. Never logs bot tokens; message text is
truncated; callback data is truncated.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("bat_telegram.update_audit")

_MAX_TEXT = 240
_MAX_DATA = 200


def _safe_text(value: Any, limit: int = _MAX_TEXT) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\n", "\\n")
    if len(s) > limit:
        return s[:limit] + f"…<{len(s)}>"
    return s


async def _audit_update(update: Any, context: Any) -> None:
    try:
        from core.money_audit import audit, new_correlation_id

        corr = new_correlation_id("tg")
        u = update
        user = getattr(u, "effective_user", None)
        chat = getattr(u, "effective_chat", None)
        base: dict[str, Any] = {
            "corr": corr,
            "update_id": getattr(u, "update_id", None),
            "user_id": getattr(user, "id", None),
            "username": getattr(user, "username", None),
            "chat_id": getattr(chat, "id", None),
            "chat_type": getattr(chat, "type", None),
        }
        msg = getattr(u, "effective_message", None) or getattr(u, "message", None)
        cq = getattr(u, "callback_query", None)
        if cq is not None:
            audit(
                "telegram.callback",
                data=_safe_text(getattr(cq, "data", None), _MAX_DATA),
                **base,
            )
            return
        if msg is not None:
            text = getattr(msg, "text", None) or getattr(msg, "caption", None) or ""
            kind = "telegram.command" if str(text).startswith("/") else "telegram.message"
            audit(
                kind,
                text=_safe_text(text),
                has_photo=bool(getattr(msg, "photo", None)),
                **base,
            )
            return
        audit("telegram.update", update_type=type(u).__name__, **base)
    except Exception as exc:
        logger.debug("update audit failed: %s", exc)


def attach_update_audit(app: Any) -> None:
    """Register TypeHandler(Update) at group -1. Idempotent per app."""
    if getattr(app, "_batman_update_audit", False):
        return
    try:
        from telegram import Update
        from telegram.ext import TypeHandler
    except Exception as exc:
        logger.warning("cannot attach update audit (ptb missing): %s", exc)
        return

    app.add_handler(TypeHandler(Update, _audit_update), group=-1)
    app._batman_update_audit = True
    logger.info("Telegram update audit attached (group=-1)")
