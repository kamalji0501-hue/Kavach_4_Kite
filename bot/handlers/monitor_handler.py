"""
Batman v3 — Telegram Monitor handler.

/status     → System & module status overview.
/legs       → Current open Batman legs with P&L (was /positions).
/pnl        → Total live P&L.
/funds      → Available margin (was /balance).
"""

from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler, ContextTypes

from bot.auth import authorized_only
from telegram import Update

logger = logging.getLogger("batman.telegram.monitor")


def register_monitor_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("legs", _cmd_positions))  # user-facing: /legs
    app.add_handler(CommandHandler("positions", _cmd_positions))  # alias — backward compat
    app.add_handler(CommandHandler("pnl", _cmd_pnl))
    app.add_handler(CommandHandler("funds", _cmd_balance))  # user-facing: /funds
    app.add_handler(CommandHandler("balance", _cmd_balance))  # alias — backward compat


# ── /status ──────────────────────────────────────────────────


@authorized_only
async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Full system status: each module's running state + key metrics."""
    modules = context.bot_data.get("modules", {})
    broker = context.bot_data["broker"]
    state = context.bot_data["state"]

    lines = ["🦇 *Batman v3 Status*\n"]

    # Module status
    for name, mod in modules.items():
        st = mod.status()
        icon = "🟢" if st["running"] else ("⚪" if st["enabled"] else "🔴")
        lines.append(f"{icon} `{name}` — {'running' if st['running'] else 'stopped'}")

    # Key state
    ato_pts = state.get("ato.retrace_points", "—")
    trailing = state.get("trailing.active", False)
    hedge = state.get("hedge.active", False)
    lines.append(f"\nATO retrace points: *{ato_pts}*")
    lines.append(f"Trailing: *{'ACTIVE' if trailing else 'off'}*")
    lines.append(f"Hedge: *{'ACTIVE' if hedge else 'off'}*")

    # Broker
    lines.append(f"\nBroker age: {broker}")

    try:
        pnl = broker.get_live_pnl()
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"Live P&L: {emoji} ₹{pnl:,.0f}")
    except Exception:
        lines.append("Live P&L: ⚠ unavailable")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /legs (/positions alias) ──────────────────────────────────────────────


@authorized_only
async def _cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show open Batman legs with individual P&L."""
    modules = context.bot_data.get("modules", {})
    monitor = modules.get("position_monitor")

    if monitor and hasattr(monitor, "get_position_summary"):
        summary = monitor.get_position_summary()
    else:
        # Fallback — query broker directly
        broker = context.bot_data["broker"]
        try:
            pnl = broker.get_live_pnl()
            positions = broker.get_positions()
            legs = []
            if positions is not None and not positions.empty:
                for _, row in positions.iterrows():
                    sym = row.get("tradingSymbol", row.get("tradingsymbol", "?"))
                    qty = int(row.get("netQty", 0))
                    legs.append({"symbol": sym, "qty": qty, "pnl": 0})
            summary = {"pnl": pnl, "legs": legs, "leg_count": len(legs)}
        except Exception as exc:
            await update.message.reply_text(f"❌ Failed: {exc}")
            return

    if "error" in summary:
        await update.message.reply_text(f"❌ {summary['error']}")
        return

    lines = ["📊 *Batman Legs*\n"]
    for leg in summary.get("legs", []):
        sym = leg["symbol"]
        qty = leg["qty"]
        pnl = leg.get("pnl", 0)
        side = "LONG" if qty > 0 else "SHORT"
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"`{sym}`\n  {side} {abs(qty)} | {emoji} ₹{pnl:,.0f}")

    total = summary.get("pnl", 0)
    total_emoji = "🟢" if total >= 0 else "🔴"
    lines.append(f"\n*Total P&L:* {total_emoji} ₹{total:,.0f}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /pnl ─────────────────────────────────────────────────────


@authorized_only
async def _cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    broker = context.bot_data["broker"]
    try:
        pnl = broker.get_live_pnl()
        emoji = "🟢" if pnl >= 0 else "🔴"
        await update.message.reply_text(f"{emoji} *Live P&L:* ₹{pnl:,.0f}", parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


# ── /funds (/balance alias) ────────────────────────────────────────────────


@authorized_only
async def _cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    broker = context.bot_data["broker"]
    try:
        bal = broker.get_balance()
        await update.message.reply_text(
            f"💰 *Available Balance:* ₹{bal:,.0f}", parse_mode="Markdown"
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")
