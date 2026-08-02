"""
Batman v3 — Telegram ATO handler.

/ato → Shows an inline keyboard with retrace-point options (5/10/35/50).
User taps a button → retrace points are updated in StateManager
and the active ATOProtection module picks up the change.

retrace_points = the cushion (in index points) the market must pull back
PAST the sell strike before the ATO position is exited on retracement.
The ATO entry trigger is always at the sell strike itself (no buffer).
"""

from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.auth import authorized_only
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

logger = logging.getLogger("batman.telegram.ato")


def register_ato_handlers(app: Application) -> None:
    """Register ATO-related handlers on the Application."""
    app.add_handler(CommandHandler("ato", _cmd_ato))
    app.add_handler(CallbackQueryHandler(_cb_ato_points, pattern=r"^ato_points_"))


@authorized_only
async def _cmd_ato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show ATO retrace-point selection keyboard."""
    state = context.bot_data["state"]
    current = state.get("ato.retrace_points", 5)
    options = context.bot_data["config"].get("ato.retrace_point_options", [5, 10, 35, 50])

    rows = []
    for pts in options:
        marker = " ✓" if pts == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{pts} pts{marker}",
                    callback_data=f"ato_points_{pts}",
                )
            ]
        )

    await update.message.reply_text(
        f"🎯 *ATO Retrace Points* (current: {current})\n"
        "Select how many points below/above the sell strike\n"
        "the market must retrace before the ATO position is exited:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )


@authorized_only
async def _cb_ato_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle retrace-point button tap."""
    query = update.callback_query
    await query.answer()

    pts = int(query.data.replace("ato_points_", ""))
    state = context.bot_data["state"]
    state.set("ato.retrace_points", pts)

    # Also call set_retrace_points on the module if it's active
    modules = context.bot_data.get("modules", {})
    ato_mod = modules.get("ato_protection")
    if ato_mod and hasattr(ato_mod, "set_retrace_points"):
        ato_mod.set_retrace_points(pts)

    await query.edit_message_text(
        f"✅ ATO retrace points set to *{pts}*",
        parse_mode="Markdown",
    )
    logger.info("ATO retrace points changed to %d via Telegram", pts)
