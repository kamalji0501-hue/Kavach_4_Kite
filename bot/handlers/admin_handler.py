"""
Batman v3 — Telegram Admin handler.

/modules           → List all modules with enabled/running state.
/enable <module>   → Enable and start a module.
/disable <module>  → Disable and stop a module.
/exit              → Emergency exit all positions.
/pause             → Pause algo (was /stop_algo).
/resume            → Resume algo (was /resume_algo).
/start_now         → Force-start algo immediately (was /force_algo).
"""

from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.auth import authorized_only
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

logger = logging.getLogger("batman.telegram.admin")


def register_admin_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("modules", _cmd_modules))
    app.add_handler(CommandHandler("enable", _cmd_enable))
    app.add_handler(CommandHandler("disable", _cmd_disable))
    app.add_handler(CommandHandler("exit", _cmd_exit))
    app.add_handler(CommandHandler("pause", _cmd_stop_algo))  # user-facing: /pause
    app.add_handler(CommandHandler("stop_algo", _cmd_stop_algo))  # alias — backward compat
    app.add_handler(CommandHandler("resume", _cmd_resume_algo))  # user-facing: /resume
    app.add_handler(CommandHandler("resume_algo", _cmd_resume_algo))  # alias — backward compat
    app.add_handler(CommandHandler("start_now", _cmd_force_algo))  # user-facing: /start_now
    app.add_handler(CommandHandler("force_algo", _cmd_force_algo))  # alias — backward compat
    app.add_handler(CommandHandler("algo_status", _cmd_algo_status))
    app.add_handler(CommandHandler("shutdown", _cmd_shutdown))
    app.add_handler(CallbackQueryHandler(_cb_exit_confirm, pattern=r"^exit_"))
    app.add_handler(CallbackQueryHandler(_cb_shutdown_confirm, pattern=r"^shutdown_"))


# ── /modules ─────────────────────────────────────────────────


@authorized_only
async def _cmd_modules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List every registered module with its current state."""
    modules = context.bot_data.get("modules", {})

    if not modules:
        await update.message.reply_text("No modules registered.")
        return

    lines = ["⚙ *Modules*\n"]
    for name, mod in modules.items():
        st = mod.status()
        enabled = "enabled" if st["enabled"] else "disabled"
        running = "🟢 running" if st["running"] else "⚪ stopped"
        lines.append(f"`{name}` — {enabled} | {running}")

    lines.append("\nUse /enable <name> or /disable <name>")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /enable ──────────────────────────────────────────────────


@authorized_only
async def _cmd_enable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable and start a module by name."""
    modules = context.bot_data.get("modules", {})
    config = context.bot_data["config"]

    args = context.args
    if not args:
        names = ", ".join(f"`{n}`" for n in modules)
        await update.message.reply_text(
            f"Usage: /enable <module>\nAvailable: {names}",
            parse_mode="Markdown",
        )
        return

    name = args[0].lower()
    mod = modules.get(name)
    if mod is None:
        await update.message.reply_text(f"❌ Unknown module: `{name}`", parse_mode="Markdown")
        return

    # Update config in memory
    config._data.setdefault("modules", {}).setdefault(name, {})["enabled"] = True

    if not mod.is_running:
        mod.start()
        await update.message.reply_text(f"✅ `{name}` enabled and started.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ `{name}` is already running.", parse_mode="Markdown")


# ── /disable ─────────────────────────────────────────────────


@authorized_only
async def _cmd_disable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop and disable a module by name."""
    modules = context.bot_data.get("modules", {})
    config = context.bot_data["config"]

    args = context.args
    if not args:
        names = ", ".join(f"`{n}`" for n in modules)
        await update.message.reply_text(
            f"Usage: /disable <module>\nAvailable: {names}",
            parse_mode="Markdown",
        )
        return

    name = args[0].lower()
    mod = modules.get(name)
    if mod is None:
        await update.message.reply_text(f"❌ Unknown module: `{name}`", parse_mode="Markdown")
        return

    # Update config in memory
    config._data.setdefault("modules", {}).setdefault(name, {})["enabled"] = False

    if mod.is_running:
        mod.stop()
        await update.message.reply_text(f"🔴 `{name}` disabled and stopped.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ `{name}` was already stopped.", parse_mode="Markdown")


# ── /exit ────────────────────────────────────────────────────


@authorized_only
async def _cmd_exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Emergency exit — confirm before closing all positions."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🚨 EXIT ALL", callback_data="exit_confirm"),
                InlineKeyboardButton("Cancel", callback_data="exit_cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        "🚨 *EMERGENCY EXIT*\n\n"
        "This will close ALL open positions immediately.\n"
        "Are you sure?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@authorized_only
async def _cb_exit_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "exit_cancel":
        await query.edit_message_text("Cancelled.")
        return

    modules = context.bot_data.get("modules", {})
    exit_mod = modules.get("emergency_exit")

    if exit_mod and hasattr(exit_mod, "execute_exit"):
        result = exit_mod.execute_exit(reason="telegram_emergency")
        success = result.get("success", False)
        orders = result.get("orders_placed", 0)
        if success:
            await query.edit_message_text(f"✅ Emergency exit complete — {orders} orders placed.")
        else:
            await query.edit_message_text(f"❌ Exit failed: {result.get('error', 'unknown')}")
    else:
        # Fallback
        broker = context.bot_data["broker"]
        config = context.bot_data["config"]
        try:
            oids = broker.close_all_positions(
                trade_type=config.get("strategy.product_type", "MARGIN")
            )
            await query.edit_message_text(f"✅ Closed all — {len(oids)} orders.")
        except Exception as exc:
            await query.edit_message_text(f"❌ {exc}")


# ── /pause (/stop_algo alias) ────────────────────────────────────────────


@authorized_only
async def _cmd_stop_algo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pause all algo trading modules without closing any positions."""
    scheduler = context.bot_data.get("algo_scheduler")
    if scheduler is None:
        await update.message.reply_text("⚠ Algo scheduler is not running.")
        return

    count = scheduler.stop_algo()
    await update.message.reply_text(
        f"🛑 *Algo Paused*\n\n"
        f"{count} trading module(s) halted.\n"
        f"All positions remain open.\n"
        f"Monitoring and safety modules continue running.\n\n"
        f"To resume: /resume (within trading window)\n"
        f"To exit positions: /exit",
        parse_mode="Markdown",
    )


# ── /resume (/resume_algo alias) ──────────────────────────────────────────


@authorized_only
async def _cmd_resume_algo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resume algo execution within the trading window."""
    scheduler = context.bot_data.get("algo_scheduler")
    if scheduler is None:
        await update.message.reply_text("⚠ Algo scheduler is not running.")
        return

    success, message = scheduler.resume_algo()
    if success:
        await update.message.reply_text(
            f"✅ *Algo Resumed*\n\n{message}",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ *Cannot resume*\n\n{message}",
            parse_mode="Markdown",
        )


# ── /start_now (/force_algo alias) ───────────────────────────


@authorized_only
async def _cmd_force_algo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Force-start algo modules immediately without waiting for the daily prompt."""
    scheduler = context.bot_data.get("algo_scheduler")
    if scheduler is None:
        await update.message.reply_text("⚠ Algo scheduler is not running.")
        return

    scheduler.force_confirm_yes()
    await update.message.reply_text(
        "🚀 *Algo force-started*\n\nModules started immediately.",
        parse_mode="Markdown",
    )


# ── /algo_status ─────────────────────────────────────────────


@authorized_only
async def _cmd_algo_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show today's algo execution state."""
    scheduler = context.bot_data.get("algo_scheduler")
    if scheduler is None:
        await update.message.reply_text("⚠ Algo scheduler is not running.")
        return

    st = scheduler.status()
    confirmed = st.get("confirmed_today")
    stopped = st.get("manually_stopped", False)

    if confirmed == "yes" and not stopped:
        state_line = "🟢 Algo is *active*"
    elif confirmed == "yes" and stopped:
        state_line = "🟡 Algo *paused* (manually stopped)"
    elif confirmed == "no":
        state_line = "⚪ Algo *skipped* for today (manual mode)"
    else:
        state_line = "⏳ Awaiting daily confirmation"

    await update.message.reply_text(
        f"📊 *Algo Status*\n\n"
        f"{state_line}\n\n"
        f"Window: `{st['confirm_time']}` – `{st['end_time']}` IST\n"
        f"Prompt sent today: {'yes' if st['prompt_sent'] else 'no'}",
        parse_mode="Markdown",
    )


# ── /shutdown ────────────────────────────────────────────────


@authorized_only
async def _cmd_shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Graceful system shutdown — stops all modules, exits process."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔴  Yes, Shutdown", callback_data="shutdown_confirm"),
                InlineKeyboardButton("✖  Cancel", callback_data="shutdown_cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        "🔴 *System Shutdown*\n\n"
        "This will:\n"
        "• Stop all running modules\n"
        "• Exit the Batman process\n\n"
        "*Positions will NOT be closed.*\n"
        "Your Dhan session stays valid — trade manually in the Dhan app.\n\n"
        "Are you sure?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@authorized_only
async def _cb_shutdown_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "shutdown_cancel":
        await query.edit_message_text("Shutdown cancelled.")
        return

    await query.edit_message_text(
        "🔴 *Shutting down Batman v3 …*\n\n"
        "All modules stopping. Process will exit in a moment.\n"
        "Positions remain open — use the Dhan app to trade manually.",
        parse_mode="Markdown",
    )

    # Signal the main thread to exit cleanly
    shutdown_event = context.bot_data.get("shutdown_event")
    if shutdown_event:
        shutdown_event.set()
        logger.info("Shutdown triggered via Telegram /shutdown command")
    else:
        logger.warning("/shutdown pressed but no shutdown_event registered")
