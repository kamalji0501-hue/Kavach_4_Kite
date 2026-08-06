"""
Batman v3 — RATRIPAL Bot (रात्रिपाल)

Standalone Hedge Box HITL + lean Status menu.
Does NOT own: Register, ATO, Positions, or deployment wizards.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bat_telegram.alive_branding import reply_alive_card
from bat_telegram.loader import load_bot_config
from bot.auth import authorized_only
from core.batman_mode import get_mode

logger = logging.getLogger("batman.ratripal")

_CB_MENU = "rtp_menu"
_CB_HB = "rtp_hb"
_BUY_TIME_OPTIONS = ("15:20", "15:25")


def _buy_time_ist(context: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    state = context.bot_data.get("state") if context is not None else None
    if state is not None:
        raw = state.get("ratripal.buy_time_ist")
        if raw in _BUY_TIME_OPTIONS:
            return str(raw)
    cfg = context.bot_data.get("config") if context is not None else None
    if cfg is not None:
        try:
            raw = str(cfg.get("hedge_box.buy_time_ist", "15:20"))
            if raw in _BUY_TIME_OPTIONS:
                return raw
        except Exception:
            pass
    return "15:20"


def _main_menu_keyboard(context: ContextTypes.DEFAULT_TYPE | None = None) -> InlineKeyboardMarkup:
    state = context.bot_data.get("state") if context is not None else None
    enabled = bool(state.get("modules.ratripal.enabled", False)) if state else False
    enable_label = "Disable" if enabled else "Enable"
    enable_action = "disable" if enabled else "enable"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⏱ Timings (hedge buy)", callback_data=f"{_CB_MENU}:timings"
                )
            ],
            [InlineKeyboardButton("📊 Positions", callback_data=f"{_CB_MENU}:positions")],
            [
                InlineKeyboardButton(
                    "🛡 Today's hedge", callback_data=f"{_CB_MENU}:today_hedge"
                )
            ],
            [
                InlineKeyboardButton("Status", callback_data=f"{_CB_MENU}:status"),
                InlineKeyboardButton(enable_label, callback_data=f"{_CB_MENU}:{enable_action}"),
            ],
            [InlineKeyboardButton("Home", callback_data=f"{_CB_MENU}:home")],
        ]
    )


def _timings_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    current = _buy_time_ist(context)
    rows: list[list[InlineKeyboardButton]] = []
    for opt in _BUY_TIME_OPTIONS:
        mark = " ✅" if opt == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{opt}{mark}", callback_data=f"{_CB_MENU}:buy_time:{opt}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("Home", callback_data=f"{_CB_MENU}:home")])
    return InlineKeyboardMarkup(rows)


def _positions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛡 Today's hedge", callback_data=f"{_CB_MENU}:today_hedge"
                )
            ],
            [InlineKeyboardButton("Home", callback_data=f"{_CB_MENU}:home")],
        ]
    )


def _hedge_box_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm", callback_data=f"{_CB_HB}:confirm:{request_id}"
                ),
                InlineKeyboardButton("❌ Deny", callback_data=f"{_CB_HB}:deny:{request_id}"),
            ]
        ]
    )


def _load_app_config():
    from core.config import Config

    root = Path(__file__).resolve().parents[3]
    return Config.load_module_settings(
        settings_path=root / "config" / "settings.json",
        env_path=root / "config" / ".env",
    )


def _check_time_ist(context: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    cfg = None
    if context is not None:
        cfg = context.bot_data.get("config")
    if cfg is not None:
        try:
            return str(cfg.get("hedge_box.check_time_ist", "15:15"))
        except Exception:
            pass
    return "15:15"


def _hb_enabled(context: ContextTypes.DEFAULT_TYPE) -> bool:
    cfg = context.bot_data.get("config")
    if cfg is None:
        return False
    try:
        return bool(cfg.get("hedge_box.enabled", False))
    except Exception:
        return False


def _alive_caption(context: ContextTypes.DEFAULT_TYPE) -> str:
    state = context.bot_data.get("state")
    enabled = bool(state.get("modules.ratripal.enabled", False)) if state else False
    mode = get_mode()
    check_time = _check_time_ist(context)
    buy_time = _buy_time_ist(context)
    now = datetime.now().astimezone().strftime("%d-%b %H:%M")
    return (
        "🟢 <b>RATRIPAL ACTIVE</b>\n"
        f"Mode {html.escape(str(mode).upper())} · check {html.escape(check_time)} · "
        f"buy {html.escape(buy_time)} IST\n"
        f"Enabled: {'yes' if enabled else 'no'} · {html.escape(now)}"
    )


async def _send_alive_menu(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_alive_card(
        message,
        _alive_caption(context),
        reply_markup=_main_menu_keyboard(context),
        bot_name="ratripal",
    )


def _status_html(context: ContextTypes.DEFAULT_TYPE) -> str:
    state = context.bot_data.get("state")
    enabled = bool(state.get("modules.ratripal.enabled", False)) if state else False
    last_run = state.get("ratripal.last_run_date") if state else None
    last_decision = state.get("ratripal.last_decision") if state else None
    pending = state.get("ratripal.pending.request_id") if state else None
    hb_enabled = _hb_enabled(context)
    check_time = _check_time_ist(context)
    buy_time = _buy_time_ist(context)

    return (
        "<b>RATRIPAL Status</b>\n\n"
        f"Enabled: <code>{'yes' if enabled else 'no'}</code>\n"
        f"Last run: <code>{html.escape(str(last_run or '—'))}</code>\n"
        f"Last decision: <code>{html.escape(str(last_decision or '—'))}</code>\n"
        f"Pending: <code>{html.escape(str(pending or 'none'))}</code>\n\n"
        f"hedge_box.enabled: <code>{'yes' if hb_enabled else 'no'}</code>\n"
        f"check_time_ist: <code>{html.escape(check_time)}</code>\n"
        f"buy_time_ist: <code>{html.escape(buy_time)}</code>"
    )


def _pending_html(context: ContextTypes.DEFAULT_TYPE) -> str:
    state = context.bot_data.get("state")
    pending = state.get("ratripal.pending.request_id") if state else None
    sent_at = state.get("ratripal.pending.sent_at") if state else None
    response = state.get("ratripal.pending.response") if state else None
    if not pending:
        return "<b>Pending</b>\n\nNo Hedge Box request waiting."
    return (
        "<b>Pending Hedge Box</b>\n\n"
        f"Request: <code>{html.escape(str(pending))}</code>\n"
        f"Sent: <code>{html.escape(str(sent_at or '—'))}</code>\n"
        f"Response: <code>{html.escape(str(response or 'waiting'))}</code>"
    )


def _load_deployment_dict(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    state = context.bot_data.get("state")
    if not state:
        return None
    path_raw = state.get("deployment.file")
    if not path_raw:
        return None
    path = Path(str(path_raw))
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("RATRIPAL failed to load deployment: %s", exc)
        return None


def _fmt_core_leg(leg: dict[str, Any] | None, label: str) -> str:
    if not isinstance(leg, dict) or not leg:
        return f"<b>{html.escape(label)}</b>\n<code>—</code>"
    symbol = str(leg.get("display_symbol") or leg.get("symbol") or "—")
    strike = leg.get("strike", "—")
    qty = leg.get("qty", "—")
    avg = leg.get("avg_price", "—")
    return (
        f"<b>{html.escape(label)}</b>\n"
        f"<code>{html.escape(symbol)}</code>\n"
        f"Strike <code>{html.escape(str(strike))}</code> · "
        f"Qty <code>{html.escape(str(qty))}</code> · "
        f"Avg <code>{html.escape(str(avg))}</code>"
    )


def _positions_html(context: ContextTypes.DEFAULT_TYPE) -> str:
    dep = _load_deployment_dict(context)
    if dep is None:
        return (
            "<b>📊 Positions</b>\n\n"
            "No confirmed deployment found.\n"
            "Register in KAVACH 2.0 first."
        )
    positions = dep.get("positions") or {}
    return (
        "<b>📊 Core Positions</b>\n\n"
        f"{_fmt_core_leg(positions.get('ce_buy'), 'CE BUY')}\n\n"
        f"{_fmt_core_leg(positions.get('ce_sell'), 'CE SELL')}\n\n"
        f"{_fmt_core_leg(positions.get('pe_buy'), 'PE BUY')}\n\n"
        f"{_fmt_core_leg(positions.get('pe_sell'), 'PE SELL')}"
    )


def _preview_today_hedge(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Compute dynamic-box hedge strikes from live spot + deployment.

    Same math as the 15:15 checkpoint module: zone from spot vs sell strikes,
    fixed BE = sell±200, color depth from that BE.
    """
    from modules.ratripal import Ratripal

    broker = context.bot_data.get("broker")
    state = context.bot_data.get("state")
    config = context.bot_data.get("config")
    event_bus = context.bot_data.get("event_bus")
    if broker is None or state is None or config is None:
        return "<b>🛡 Today's hedge</b>\n\n⚠️ Broker/state not ready."

    mod = Ratripal(broker, config, state, event_bus)
    deployment = mod._load_deployment()
    if deployment is None:
        return (
            "<b>🛡 Today's hedge</b>\n\n"
            "No deployment file — register in KAVACH 2.0 first."
        )

    try:
        spot = float(broker.get_nifty_ltp())
    except Exception as exc:
        return f"<b>🛡 Today's hedge</b>\n\n⚠️ Spot unavailable: {html.escape(str(exc))}"

    today = date.today()
    dte = mod._calculate_dte(deployment, today)
    buy_time = _buy_time_ist(context)
    check_time = _check_time_ist(context)
    plans = mod._build_plans(deployment, spot, dte)
    positions = deployment.get("positions") or {}
    ce_sell = (positions.get("ce_sell") or {}).get("strike", "—")
    pe_sell = (positions.get("pe_sell") or {}).get("strike", "—")

    lines = [
        "<b>🛡 Today's hedge</b>",
        "",
        f"Spot: <code>{spot:,.2f}</code>",
        f"DTE: <code>{dte}</code>",
        f"CE sell: <code>{html.escape(str(ce_sell))}</code> · "
        f"PE sell: <code>{html.escape(str(pe_sell))}</code>",
        f"Plan at: <code>{html.escape(check_time)}</code> · "
        f"Buy at: <code>{html.escape(buy_time)}</code>",
        "",
    ]
    if dte <= 0:
        lines.append("0DTE — no Hedge Box buys today.")
        return "\n".join(lines)

    for plan in plans:
        lines.append(
            f"<b>{html.escape(plan.side)}</b> · zone {html.escape(plan.state)} · "
            f"{html.escape(plan.action)}"
        )
        if plan.break_even is not None:
            lines.append(f"BE <code>{plan.break_even}</code>")
        if plan.strike and plan.symbol:
            lines.append(
                f"Buy strike <code>{plan.strike}</code> · "
                f"Qty <code>{plan.quantity}</code>\n"
                f"<code>{html.escape(plan.symbol)}</code>"
            )
        else:
            lines.append("<code>— no buy</code>")
        lines.append("")

    eligible = [p for p in plans if mod._is_buy_candidate(p)]
    if not eligible:
        lines.append("No eligible buy candidates at this spot.")
    else:
        lines.append(f"Eligible sides now: <code>{len(eligible)}</code>")
    return "\n".join(lines).rstrip()


async def _reply_with_menu(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if query.message is None:
        return
    await query.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup or _main_menu_keyboard(context),
    )


@authorized_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    await _send_alive_menu(update.effective_message, context)


@authorized_only
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    await _send_alive_menu(update.effective_message, context)


@authorized_only
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    await _send_alive_menu(update.effective_message, context)


@authorized_only
async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    prefix = f"{_CB_MENU}:"
    if not data.startswith(prefix):
        return
    rest = data[len(prefix) :]
    state = context.bot_data.get("state")

    # buy_time payloads are "buy_time:15:20" — do not split on ':' beyond the key.
    if rest.startswith("buy_time:"):
        chosen = rest[len("buy_time:") :]
        if chosen not in _BUY_TIME_OPTIONS or not state:
            await _reply_with_menu(query, context, "⚠️ Invalid buy time.")
            return
        state.set("ratripal.buy_time_ist", chosen)
        await _reply_with_menu(
            query,
            context,
            f"✅ Hedge buy time set to <code>{html.escape(chosen)}</code> IST.",
            reply_markup=_timings_keyboard(context),
        )
        return

    action = rest.split(":", 1)[0]

    if action == "status":
        await _reply_with_menu(query, context, _status_html(context))
        return

    if action == "home":
        if query.message is not None:
            await _send_alive_menu(query.message, context)
        return

    if action == "timings":
        current = _buy_time_ist(context)
        await _reply_with_menu(
            query,
            context,
            "<b>⏱ Hedge buy timing</b>\n\n"
            f"Current: <code>{html.escape(current)}</code>\n"
            "Pick when RATRIPAL places the hedge buy after the 15:15 plan.",
            reply_markup=_timings_keyboard(context),
        )
        return

    if action == "positions":
        await _reply_with_menu(
            query,
            context,
            _positions_html(context),
            reply_markup=_positions_keyboard(),
        )
        return

    if action == "today_hedge":
        await _reply_with_menu(
            query,
            context,
            _preview_today_hedge(context),
            reply_markup=_positions_keyboard(),
        )
        return

    if action in {"enable", "disable"}:
        if not state:
            await _reply_with_menu(query, context, "⚠️ State unavailable.")
            return
        turn_on = action == "enable"
        state.set("modules.ratripal.enabled", turn_on)
        label = "enabled" if turn_on else "disabled"
        await _reply_with_menu(
            query,
            context,
            f"{'✅' if turn_on else '⏸'} RATRIPAL {label}.",
        )
        return


@authorized_only
async def on_hedge_box_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    payload = (query.data or "").split(":", 2)
    if len(payload) != 3:
        await query.edit_message_text("⚠️ Invalid Hedge Box response.")
        return

    _, decision, request_id = payload
    state = context.bot_data.get("state")
    current_request = state.get("ratripal.pending.request_id") if state else None
    if not state or current_request != request_id:
        await query.edit_message_text("⚠️ This Hedge Box request expired or was already handled.")
        return

    state.set("ratripal.pending.response", decision)
    state.set("ratripal.pending.responded_at", datetime.now().astimezone().isoformat())

    if decision == "deny":
        await query.edit_message_text("❌ Hedge Box denied for today.")
        return

    buy_time = _buy_time_ist(context)
    await query.edit_message_text(
        f"✅ Hedge Box confirmed — buys at <b>{html.escape(buy_time)}</b> IST.",
        parse_mode=ParseMode.HTML,
    )


async def _push_html(app: Application, chat_id: str, text: str, reply_markup=None) -> None:
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except Exception as exc:
        logger.error("RATRIPAL push failed: %s", exc)


def register_event_subscriptions(app: Application) -> None:
    bus = app.bot_data.get("event_bus")
    chat_id = app.bot_data.get("chat_id", "")
    if not bus or not chat_id:
        logger.warning("RATRIPAL: event_bus or chat_id missing — skipping subscriptions")
        return

    from core.event_bus import Event

    def _fire(coro) -> None:
        loop = app.bot_data.get("loop")
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, loop)

            def _log_future_result(fut: asyncio.Future) -> None:
                try:
                    fut.result()
                except Exception as exc:
                    logger.error("RATRIPAL event push failed: %s", exc)

            future.add_done_callback(_log_future_result)
        else:
            logger.warning("RATRIPAL: event loop not available — push skipped")

    def _on_hedge_box_prompt(event, payload):
        del event

        async def _send_prompt() -> None:
            request_id = str(payload.get("request_id", ""))
            dte = payload.get("dte", "?")
            spot = payload.get("spot")
            buy_time = payload.get("buy_time_ist") or "15:20"
            timeout_seconds = int(payload.get("timeout_seconds", 120) or 120)
            sides = payload.get("sides", [])
            spot_line = (
                f"{float(spot):,.2f}" if isinstance(spot, (int, float)) else "N/A"
            )
            lines = [
                "<b>Hedge Box Plan</b>",
                "",
                f"Spot: <code>{html.escape(spot_line)}</code>",
                f"DTE: <code>{html.escape(str(dte))}</code>",
                f"Buy: <code>{html.escape(str(buy_time))}</code>",
                f"Timeout: <code>{timeout_seconds}s</code>",
                "",
            ]
            for side in sides:
                lines.append(
                    f"<b>{html.escape(str(side.get('side', '?')))}</b> · "
                    f"{html.escape(str(side.get('zone', '?')))} · "
                    f"<code>{html.escape(str(side.get('strike', '-')))}</code> · "
                    f"qty <code>{html.escape(str(side.get('qty', '-')))}</code>"
                )
            lines.extend(
                ["", "Confirm to buy at buy-time · Deny to skip today · No reply auto-proceeds."]
            )
            await _push_html(
                app,
                chat_id,
                "\n".join(lines),
                reply_markup=_hedge_box_keyboard(request_id),
            )

        _fire(_send_prompt())

    def _on_hedge_box_executed(event, payload):
        del event
        side = html.escape(str(payload.get("side", "?")))
        symbol = html.escape(str(payload.get("symbol", "?")))
        qty = html.escape(str(payload.get("qty", "?")))
        order_id = html.escape(str(payload.get("order_id", "?")))
        _fire(
            _push_html(
                app,
                chat_id,
                f"✅ <b>Buy verified</b> · {side} · <code>{symbol}</code> · "
                f"qty <code>{qty}</code> · order <code>{order_id}</code>",
            )
        )

    bus.subscribe(Event.HEDGE_BOX_CONFIRMATION_REQUEST, _on_hedge_box_prompt)
    bus.subscribe(Event.HEDGE_BOX_EXECUTED, _on_hedge_box_executed)
    logger.info("RATRIPAL: event subscriptions registered ✓")


async def _on_handler_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    logger.error("RATRIPAL handler error: %s", err, exc_info=err)


def build_application(broker=None, state=None, event_bus=None, config=None) -> Application:
    """Build and return the RATRIPAL PTB Application."""
    cfg = load_bot_config("ratripal")

    app = (
        Application.builder()
        .token(cfg.bot_token)
        .concurrent_updates(True)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(60.0)
        .media_write_timeout(60.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(30.0)
        .build()
    )

    app.bot_data["broker"] = broker
    app.bot_data["state"] = state
    app.bot_data["event_bus"] = event_bus
    app.bot_data["chat_id"] = str(cfg.chat_id).strip()
    app.bot_data["params"] = cfg.params
    if config is not None:
        app.bot_data["config"] = config
    else:
        try:
            app.bot_data["config"] = _load_app_config()
        except Exception as exc:
            logger.warning("RATRIPAL config load failed: %s", exc)
            app.bot_data["config"] = None

    # Default buy time if operator has not chosen yet.
    if state is not None and not state.get("ratripal.buy_time_ist"):
        default_buy = "15:20"
        try:
            if app.bot_data.get("config") is not None:
                default_buy = str(
                    app.bot_data["config"].get("hedge_box.buy_time_ist", "15:20")
                )
        except Exception:
            pass
        if default_buy in _BUY_TIME_OPTIONS:
            state.set("ratripal.buy_time_ist", default_buy, save=False)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CallbackQueryHandler(on_hedge_box_callback, pattern=f"^{_CB_HB}:"))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=f"^{_CB_MENU}:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(_on_handler_error)

    register_event_subscriptions(app)

    async def _post_init(application: Application) -> None:
        application.bot_data["loop"] = asyncio.get_running_loop()
        logger.info("RATRIPAL event loop bound for EventBus dispatch")
        chat_id = str(application.bot_data.get("chat_id") or "").strip()
        if not chat_id:
            return
        try:

            class _Ctx:
                bot_data = application.bot_data

            ctx = _Ctx()
            caption = _alive_caption(ctx)  # type: ignore[arg-type]
            await application.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_keyboard(ctx),  # type: ignore[arg-type]
            )
            logger.info("RATRIPAL online notice sent to chat_id=%s", chat_id)
        except Exception as exc:
            logger.warning("RATRIPAL online notice failed: %s", exc)

    app.post_init = _post_init

    logger.info("RATRIPAL bot application built ✓")
    return app
