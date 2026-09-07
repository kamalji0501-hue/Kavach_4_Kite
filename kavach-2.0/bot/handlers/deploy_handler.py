"""
Batman v3 — Telegram Deploy handler.

/choose           → Read open positions, choose 4 Batman legs, arm the algo.
/batman_complete  → Batman positions closed — full cleanup and algo reset.
/close_all        → Close all positions immediately.
"""

from __future__ import annotations

import logging
from typing import Any

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.auth import authorized_only
from core.utils import build_ato_symbols, parse_option_symbol
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

logger = logging.getLogger("batman.telegram.deploy")


def _parse_symbol(sym: str):
    """Return (prefix, strike, opt_type) or (None, None, None) on failure."""
    return parse_option_symbol(sym)


def _classify_legs(selected: list[dict[str, Any]]) -> dict[str, dict] | None:
    """Map 4 selected positions → {ce_sell, pe_sell, ce_buy, pe_buy}.

    Returns None if classification fails (wrong counts or unparseable symbols).
    """
    result: dict[str, dict | None] = {
        "ce_sell": None,
        "pe_sell": None,
        "ce_buy": None,
        "pe_buy": None,
    }
    for pos in selected:
        sym = pos.get("tradingSymbol", "")
        qty = pos.get("netQty", 0)
        _, _, opt_type = _parse_symbol(sym)
        if opt_type is None:
            return None
        if qty < 0:
            key = "ce_sell" if opt_type == "CE" else "pe_sell"
        else:
            key = "ce_buy" if opt_type == "CE" else "pe_buy"
        if result[key] is not None:
            return None  # duplicate classification
        result[key] = pos

    if any(v is None for v in result.values()):
        return None
    return result


def _to_state_leg(pos: dict[str, Any]) -> dict[str, Any]:
    """Convert a broker position dict to the state leg format."""
    sym = pos.get("tradingSymbol", "")
    qty = pos.get("netQty", 0)
    _, strike, _ = _parse_symbol(sym)
    avg_price = pos.get("buyAvg", 0) if qty > 0 else pos.get("sellAvg", 0)
    return {
        "symbol": sym,
        "strike": strike or 0,
        "qty": qty,
        "order_id": "manual",
        "avg_price": float(avg_price),
    }


def register_deploy_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("choose", _cmd_confirm_deploy))  # user-facing: /choose
    app.add_handler(
        CommandHandler("confirm_deploy", _cmd_confirm_deploy)
    )  # alias — backward compat
    app.add_handler(CommandHandler("batman_complete", _cmd_batman_complete))
    app.add_handler(CommandHandler("close_all", _cmd_close_all))
    # Legacy
    app.add_handler(CommandHandler("deploy", _cmd_deploy))
    app.add_handler(CallbackQueryHandler(_cb_confirm_deploy, pattern=r"^deploy_"))
    app.add_handler(CallbackQueryHandler(_cb_confirm_close, pattern=r"^close_all_"))
    app.add_handler(CallbackQueryHandler(_cb_pos_toggle, pattern=r"^pos_toggle:"))
    app.add_handler(CallbackQueryHandler(_cb_pos_confirm, pattern=r"^pos_confirm:"))
    app.add_handler(CallbackQueryHandler(_cb_batman_complete_ans, pattern=r"^batman_complete:"))


# ── /choose (/confirm_deploy alias) ──────────────────────────────────────────


@authorized_only
async def _cmd_confirm_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Fetch all open broker positions, show toggleable list, ask user to choose
    the 4 Batman legs, then double-confirm before loading into state.
    """
    state = context.bot_data["state"]

    # Guard: already confirmed this cycle
    if state.get("deployment.confirmed", False):
        await update.message.reply_text(
            "⚠️ Batman is already active this cycle.\n"
            "Use /batman\\_complete first to reset before choosing new legs.",
            parse_mode="Markdown",
        )
        return

    broker = context.bot_data["broker"]
    try:
        positions = broker.get_positions()
    except Exception as exc:
        await update.message.reply_text(f"❌ Failed to fetch positions: {exc}")
        return

    if not positions:
        await update.message.reply_text(
            "📭 No open positions found.\n" "Please deploy Batman on Dhan first, then run /choose.",
            parse_mode="Markdown",
        )
        return

    # Store in user_data for toggle session
    context.user_data["pending_legs"] = {
        "positions": positions,
        "selected": set(),
    }

    await update.message.reply_text(
        "🦇 *Choose Your 4 Batman Legs*\n\n"
        "Tap each Batman position to select it (✅ = selected).\n"
        "Select exactly 4 legs, then tap *Confirm selection*.",
        reply_markup=_build_pos_keyboard(positions, set()),
        parse_mode="Markdown",
    )


def _build_pos_keyboard(
    positions: list,
    selected: set,
    show_confirm: bool = False,
) -> InlineKeyboardMarkup:
    """Build the inline keyboard for position toggle selection."""
    rows = []
    for i, pos in enumerate(positions):
        sym = pos.get("tradingSymbol", f"Pos{i}")
        qty = pos.get("netQty", 0)
        side = "SELL" if qty < 0 else "BUY"
        mark = "✅ " if i in selected else "   "
        label = f"{mark}{sym} ({side} {abs(qty)})"
        rows.append([InlineKeyboardButton(label, callback_data=f"pos_toggle:{i}")])

    if show_confirm:
        rows.append(
            [
                InlineKeyboardButton("✔️ Confirm selection", callback_data="pos_confirm:yes"),
                InlineKeyboardButton("❌ Cancel", callback_data="pos_confirm:cancel"),
            ]
        )
    return InlineKeyboardMarkup(rows)


@authorized_only
async def _cb_pos_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle a position in/out of the selection set."""
    query = update.callback_query
    await query.answer()

    pending = context.user_data.get("pending_legs")
    if pending is None:
        await query.edit_message_text("Session expired. Run /choose again.")
        return

    idx = int(query.data.split(":", 1)[1])
    selected: set = pending["selected"]
    positions = pending["positions"]

    if idx in selected:
        selected.discard(idx)
    else:
        selected.add(idx)

    show_confirm = len(selected) == 4
    await query.edit_message_reply_markup(
        reply_markup=_build_pos_keyboard(positions, selected, show_confirm)
    )


@authorized_only
async def _cb_pos_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all pos_confirm:* callbacks from the position-selection flow."""
    query = update.callback_query
    await query.answer()
    action = (
        query.data
    )  # "pos_confirm:yes" | "pos_confirm:load" | "pos_confirm:redo" | "pos_confirm:cancel"

    if action == "pos_confirm:cancel":
        context.user_data.pop("pending_legs", None)
        context.user_data.pop("pending_classified", None)
        await query.edit_message_text("❌ Cancelled.")
        return

    if action == "pos_confirm:yes":
        # ── First confirmation step: show double-confirm with classified legs ──
        pending = context.user_data.get("pending_legs")
        if pending is None:
            await query.edit_message_text("Session expired. Run /choose again.")
            return

        positions = pending["positions"]
        selected = pending["selected"]

        if len(selected) != 4:
            await query.edit_message_text("⚠ Select exactly 4 legs first.")
            return

        sel_positions = [positions[i] for i in sorted(selected)]
        legs = _classify_legs(sel_positions)
        if legs is None:
            await query.edit_message_text(
                "❌ Could not classify the selected 4 legs.\n"
                "Ensure you selected 1 CE sell, 1 CE buy, 1 PE sell, 1 PE buy.",
            )
            return

        context.user_data["pending_classified"] = legs

        ce_sell_sym = legs["ce_sell"]["tradingSymbol"]
        pe_sell_sym = legs["pe_sell"]["tradingSymbol"]
        ce_buy_sym = legs["ce_buy"]["tradingSymbol"]
        pe_buy_sym = legs["pe_buy"]["tradingSymbol"]

        text = (
            "🦇 *Confirm Batman Legs*\n\n"
            f"CE Sell : `{ce_sell_sym}` ({abs(legs['ce_sell']['netQty'])} qty)\n"
            f"PE Sell : `{pe_sell_sym}` ({abs(legs['pe_sell']['netQty'])} qty)\n"
            f"CE Buy  : `{ce_buy_sym}` ({abs(legs['ce_buy']['netQty'])} qty)\n"
            f"PE Buy  : `{pe_buy_sym}` ({abs(legs['pe_buy']['netQty'])} qty)\n\n"
            "Load these 4 legs and start ATO monitoring?"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Yes, load & monitor", callback_data="pos_confirm:load"
                    ),
                    InlineKeyboardButton("🔙 Re-select", callback_data="pos_confirm:redo"),
                ]
            ]
        )
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    if action == "pos_confirm:redo":
        pending = context.user_data.get("pending_legs")
        context.user_data.pop("pending_classified", None)
        if pending:
            pending["selected"] = set()
            await query.edit_message_text(
                "🦇 *Select 4 legs again.*",
                reply_markup=_build_pos_keyboard(pending["positions"], set()),
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("Session expired. Run /choose again.")
        return

    if action == "pos_confirm:load":
        # ── Final step: commit to state ───────────────────────────────────────
        legs = context.user_data.pop("pending_classified", None)
        context.user_data.pop("pending_legs", None)

        if legs is None:
            await query.edit_message_text("Session expired. Run /choose again.")
            return

        state = context.bot_data["state"]
        config = context.bot_data["config"]
        events = context.bot_data["events"]

        strike_step = config.get("ato.strike_offset", 50)

        for leg_key, pos in legs.items():
            state.set(f"positions.{leg_key}", _to_state_leg(pos), save=False)

        ce_sell_sym = legs["ce_sell"]["tradingSymbol"]
        pe_sell_sym = legs["pe_sell"]["tradingSymbol"]
        _, ce_sell_strike, _ = _parse_symbol(ce_sell_sym)
        _, pe_sell_strike, _ = _parse_symbol(pe_sell_sym)

        ato = build_ato_symbols(ce_sell_sym, pe_sell_sym, strike_step=strike_step)
        ce_ato_sym = ato["ce_protect_symbol"] or ""
        pe_ato_sym = ato["pe_protect_symbol"] or ""
        ce_ato_strike = ato["ce_protect_strike"]
        pe_ato_strike = ato["pe_protect_strike"]

        state.set("ato.ce_protect_symbol", ce_ato_sym, save=False)
        state.set("ato.ce_protect_strike", ce_ato_strike, save=False)
        state.set("ato.pe_protect_symbol", pe_ato_sym, save=False)
        state.set("ato.pe_protect_strike", pe_ato_strike, save=False)

        from core.utils import today_ist

        state.set("deployment.confirmed", True, save=False)
        state.set("deployment.batman_complete", False, save=False)
        state.set("deployment.positions_confirmed_date", today_ist().isoformat(), save=False)
        state.save()

        from core.event_bus import Event

        events.publish(
            Event.DEPLOYMENT_CONFIRMED,
            {
                "legs": {k: v["tradingSymbol"] for k, v in legs.items()},
            },
        )

        ce_buy_sym = legs["ce_buy"]["tradingSymbol"]
        pe_buy_sym = legs["pe_buy"]["tradingSymbol"]
        await query.edit_message_text(
            "✅ *Batman Deployed — ATO Monitoring Active*\n\n"
            f"CE Sell: `{ce_sell_sym}` | CE Buy: `{ce_buy_sym}`\n"
            f"PE Sell: `{pe_sell_sym}` | PE Buy: `{pe_buy_sym}`\n\n"
            f"ATO range:\n"
            f"  CE breach ≥ {ce_sell_strike} → buy `{ce_ato_sym}`\n"
            f"  PE breach ≤ {pe_sell_strike} → buy `{pe_ato_sym}`",
            parse_mode="Markdown",
        )


# ── /batman_complete ──────────────────────────────────────────────────────────


@authorized_only
async def _cmd_batman_complete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for confirmation then fully clean up Batman state — algo reset.

    Run this whenever you are done with a deployed Batman — whether at expiry
    or mid-week.  After confirmation:
      * All algo modules are stopped
      * Positions, ATO symbols/strikes, and deployment flags are cleared
      * System is instantly ready for a fresh /confirm_deploy
    """
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes — Batman complete", callback_data="batman_complete:confirm"
                ),
                InlineKeyboardButton("❌ Cancel", callback_data="batman_complete:cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        "🦇 *Batman Complete?*\n\n"
        "This will:\n"
        "• Stop all algo modules (ATO, trailing, hedge)\n"
        "• Clear all deployment data (positions, ATO strikes, flags)\n"
        "• Reset the algo — ready for your next deployment\n\n"
        "Your open positions on Dhan are *not* closed automatically.\n"
        "Run /confirm\\_deploy any time after your next deployment.",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@authorized_only
async def _cb_batman_complete_ans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "batman_complete:cancel":
        await query.edit_message_text("Cancelled. Batman monitoring continues.")
        return

    state = context.bot_data["state"]
    events = context.bot_data["events"]
    modules = context.bot_data.get("modules", {})
    config = context.bot_data["config"]

    # ── Stop all algo modules ─────────────────────────────────────────────────
    algo_module_names = config.get(
        "operations.algo_modules",
        ["ato_protection", "profit_trailing"],
    )
    stopped = []
    for name in algo_module_names:
        mod = modules.get(name)
        if mod and mod.is_running:
            mod.stop()
            stopped.append(name)

    # Full state cleanup — idle until next Register
    from core.batman_cleanup import reset_state_after_complete

    reset_state_after_complete(state)

    from core.event_bus import Event

    events.publish(Event.BATMAN_COMPLETE, {})

    stopped_text = ", ".join(stopped) if stopped else "none running"
    await query.edit_message_text(
        f"✅ *Batman Complete — Algo Reset*\n\n"
        f"Modules stopped: {stopped_text}\n"
        f"All deployment data cleared (positions, ATO strikes, order IDs)\n\n"
        f"System is fresh and ready.\n"
        f"Deploy on Dhan, then run /confirm\\_deploy whenever you\\'re ready.",
        parse_mode="Markdown",
    )


# ── /close_all ────────────────────────────────────────────────────────────────


@authorized_only
async def _cmd_close_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Close all positions — asks for confirmation first."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔴 YES — Close ALL", callback_data="close_all_confirm"),
                InlineKeyboardButton("Cancel", callback_data="close_all_cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        "⚠ *Close ALL positions?*\nThis cannot be undone.",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@authorized_only
async def _cb_confirm_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "close_all_cancel":
        await query.edit_message_text("Cancelled.")
        return

    modules = context.bot_data.get("modules", {})
    exit_mod = modules.get("emergency_exit")

    if exit_mod and hasattr(exit_mod, "execute_exit"):
        result = exit_mod.execute_exit(reason="telegram_close_all")
        orders = result.get("orders_placed", 0)
        await query.edit_message_text(
            f"✅ Emergency exit executed — {orders} close orders placed.",
        )
    else:
        broker = context.bot_data["broker"]
        config = context.bot_data["config"]
        product = config.get("strategy.product_type", "MARGIN")
        try:
            oids = broker.close_all_positions(trade_type=product)
            await query.edit_message_text(f"✅ Closed all positions — {len(oids)} orders placed.")
        except Exception as exc:
            await query.edit_message_text(f"❌ Close failed: {exc}")


# ── /deploy (legacy) ──────────────────────────────────────────────────────────


@authorized_only
async def _cmd_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy: start BatmanEntry module. Now superseded by /confirm_deploy."""
    await update.message.reply_text(
        "ℹ *Note:* Batman is now deployed manually on Dhan.\n"
        "Use /confirm\\_deploy to load your positions into Batman.",
        parse_mode="Markdown",
    )


@authorized_only
async def _cb_confirm_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "ℹ Use /confirm\\_deploy to load existing positions.",
        parse_mode="Markdown",
    )
