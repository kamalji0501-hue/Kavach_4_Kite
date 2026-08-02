"""
Batman v3 — Telegram Hedge handler.

/hedge        → Place overnight OTM CE+PE hedge.
/close_hedge  → Close the outstanding hedge.
"""

from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.auth import authorized_only
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

logger = logging.getLogger("batman.telegram.hedge")


def register_hedge_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("hedge", _cmd_hedge))
    app.add_handler(CommandHandler("close_hedge", _cmd_close_hedge))
    app.add_handler(CallbackQueryHandler(_cb_confirm_hedge, pattern=r"^hedge_"))


@authorized_only
async def _cmd_hedge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for confirmation, then place overnight hedge."""
    config = context.bot_data["config"]
    broker = context.bot_data["broker"]
    hedge_cfg = config.get("hedge", {})
    distance = hedge_cfg.get("distance_from_spot", 500)
    lots = hedge_cfg.get("lots", 1)

    try:
        spot = broker.get_nifty_ltp()
    except Exception:
        spot = 0

    text = (
        f"🛡 *Place Overnight Hedge?*\n\n"
        f"Spot: {spot:,.1f}\n"
        f"Distance: {distance} pts from spot\n"
        f"Lots: {lots}\n"
        f"CE hedge ≈ {spot + distance:,.0f} | PE hedge ≈ {spot - distance:,.0f}\n\n"
        f"This buys 1 lot OTM CE + 1 lot OTM PE."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Place Hedge", callback_data="hedge_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="hedge_cancel"),
            ]
        ]
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


@authorized_only
async def _cb_confirm_hedge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "hedge_cancel":
        await query.edit_message_text("Hedge cancelled.")
        return

    modules = context.bot_data.get("modules", {})
    hedge_mod = modules.get("overnight_hedge")

    if hedge_mod is None:
        await query.edit_message_text("⚠ OvernightHedge module not registered.")
        return

    # Trigger hedge placement directly
    config = context.bot_data["config"]
    strat = config.get("strategy", {})
    hedge_cfg = config.get("hedge", {})

    try:
        hedge_mod._place_hedge(
            index=strat.get("index", "NIFTY"),
            distance=hedge_cfg.get("distance_from_spot", 500),
            hedge_lots=hedge_cfg.get("lots", 1),
            lot_size=strat.get("lot_size", 75),
            product=strat.get("product_type", "MARGIN"),
        )
        await query.edit_message_text("✅ Overnight hedge placed!")
    except Exception as exc:
        await query.edit_message_text(f"❌ Hedge failed: {exc}")


@authorized_only
async def _cmd_close_hedge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Close outstanding hedge positions."""
    modules = context.bot_data.get("modules", {})
    hedge_mod = modules.get("overnight_hedge")

    if hedge_mod and hasattr(hedge_mod, "close_hedge"):
        try:
            hedge_mod.close_hedge()
            await update.message.reply_text("✅ Hedge positions closed.")
        except Exception as exc:
            await update.message.reply_text(f"❌ Close hedge failed: {exc}")
    else:
        await update.message.reply_text("⚠ OvernightHedge module not available.")
