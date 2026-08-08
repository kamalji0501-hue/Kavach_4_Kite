"""
Batman v3 — DRISHTI Bot (दृष्टि)

Bot 1 of 3.  Runs as an asyncio task inside ``main.py``.

Responsibilities (LOCKED 2026-04-04):
    • Dhan access-token delivery + hot-reload (daily JWT)
    • /update_token  — proactively ask user to send a fresh token
    • /deactivate_token — revoke the current token immediately
    • /health        — full broker + system health report
    • /ping          — liveness check
    • /status        — token age + expiry countdown
    • Scheduled token reminders (09:00 / 15:30 / 23:00 IST, weekdays only)
    • Market-hours connection monitor (LTP health check every hour)
    • AlgoScheduler daily start-time prompt + EOD batman-complete reminder

Does NOT own: trading commands, /pnl, strike management.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import zoneinfo
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any

from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bat_telegram.bots.drishti.nifty_feed_integration import (
    deactivate_ltp_feed,
    ensure_default_feed_config,
    feed_callback_prefix,
    feed_recovery_watchdog_loop,
    feed_watchdog_loop,
    format_feed_health_block,
    format_feed_status_line,
    format_nifty_status_html,
    format_uat_dashboard_html,
    is_uat_market_replay_running,
    on_feed_setup_callback,
    reply_gift_nifty_ltp,
    reply_live_price,
    reply_nifty_ltp_from_cache,
    restart_nifty_feed,
    uat_market_replay_watchdog_loop,
    uat_speed_keyboard,
)
from bat_telegram.control import guard_paused_command
from bat_telegram.incident_publisher import publish_incident, resolve_incident
from bat_telegram.loader import load_bot_config
from core.bot_process_status import BotRunState, classify_bot
from core.telegram_runtime import (
    cleanup_managed_runtime,
    create_managed_task,
    register_shutdown_callback,
)
from core.batman_mode import access_token_path
from core.token_store import TokenStore
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

logger = logging.getLogger("batman.drishti")
_CB_FLEET = "drishti_fleet"
_CB_MENU = "drishti_menu"
_DRISHTI_TOKEN_ENV = (
    Path(__file__).resolve().parents[3] / "telegram" / "bots" / "drishti" / "token.env"
)

# ── Token store (same file used by the live broker) ──────────────────────────
_TOKEN_STORE = TokenStore(path=access_token_path())

# Per-chat conversation state: waiting for user to paste a Dhan JWT
_AWAITING_TOKEN_KEY = "awaiting_dhan_token"

# ── IST quiet hours for *outbound* reminders (bot accepts 24/7) ──────────────
_QUIET_START = dt_time(8, 0)
_QUIET_END = dt_time(23, 30)
_IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# Market hours for TYPE 2 health monitor
_MARKET_START = dt_time(9, 15)
_MARKET_END = dt_time(15, 30)

_READ_ONLY_COMMANDS = {
    "start",
    "ping",
    "status",
    "health",
    "nifty_ltp",
    "nifty_status",
    "niftystatus",
}  # fleet_status disabled Phase 1


def _format_nifty_ltp_card(ltp: float, source: str, now: str | None = None) -> str:
    """Standard NIFTY LTP card shown after fetch or token validation."""
    ts = now or datetime.now(_IST).strftime("%d-%b-%Y %H:%M:%S IST")
    return (
        "📈 <b>NIFTY LTP</b>\n\n"
        f"💰 <b>Price: ₹{ltp:,.2f}</b>\n"
        f"🕒 <b>Time:</b> {html.escape(ts)}\n"
        f"📡 <b>Source:</b> {html.escape(source)}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _is_jwt(text: str) -> bool:
    """Heuristic: looks like a Dhan JWT access token."""
    t = text.strip()
    return len(t) > 30 and not t.startswith("/") and " " not in t and "." in t


def _set_awaiting_token(context: ContextTypes.DEFAULT_TYPE | None, value: bool) -> None:
    if context is not None:
        context.user_data[_AWAITING_TOKEN_KEY] = value


def _is_awaiting_token(context: ContextTypes.DEFAULT_TYPE | None) -> bool:
    if context is None:
        return False
    return bool(context.user_data.get(_AWAITING_TOKEN_KEY, False))


def _escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


def _token_summary() -> str:
    """Enhanced token status with visual progress indicators."""
    tok, saved_at = _TOKEN_STORE.load()
    if not tok:
        return "🔑 <b>Token Status</b>\n\n🔴 <b>No token stored</b>"

    age_h = _TOKEN_STORE.token_age_hours() or 0
    expires_in = _TOKEN_STORE.effective_expires_in_hours()
    if expires_in is None:
        expires_in = max(0.0, 24.0 - age_h)
    saved_fmt = saved_at.strftime("%d-%b %H:%M") if saved_at else "unknown"
    jwt_exp = _TOKEN_STORE.jwt_expires_at_local()
    jwt_line = jwt_exp.strftime("%d-%b %H:%M %Z") if jwt_exp else "N/A"

    # Visual status indicator
    if expires_in > 12:
        status_icon = "🟢"  # Green
        status_text = "Healthy"
    elif expires_in > 4:
        status_icon = "🟡"  # Yellow
        status_text = "Expiring Soon"
    elif expires_in > 0:
        status_icon = "🟠"  # Orange
        status_text = "Critical"
    else:
        status_icon = "🔴"  # Red
        status_text = "Expired"

    # Progress bar for token lifetime (24h total)
    progress_percent = min(100, int((expires_in / 24.0) * 100))
    filled_blocks = int(progress_percent / 10)
    empty_blocks = 10 - filled_blocks
    progress_bar = "█" * filled_blocks + "░" * empty_blocks

    return (
        f"🔑 <b>Token Status</b>\n\n"
        f"{status_icon} <b>{status_text}</b>\n\n"
        f"🕒 <b>Age:</b> {age_h:.1f} hours\n"
        f"⏳ <b>Expires in:</b> {expires_in:.1f} hours\n"
        f"🔐 <b>JWT exp:</b> {html.escape(jwt_line)}\n"
        f"📅 <b>Saved at:</b> {saved_fmt} IST\n\n"
        f"📊 <b>Lifetime Progress</b>\n"
        f"[{progress_bar}] {progress_percent}%"
    )


def should_send_type1_token_reminder(
    *,
    has_token: bool,
    expires_in_hours: float | None,
    warning_minutes: int,
) -> bool:
    """TYPE 1 reminders — fire when missing, expired, or within warning window."""
    if not has_token:
        return True
    if expires_in_hours is None:
        return True
    if expires_in_hours <= 0:
        return True
    if expires_in_hours * 60.0 <= float(warning_minutes):
        return True
    return False


def _build_health_report_html(app: Application | None = None) -> str:
    tok, saved_at = _TOKEN_STORE.load()
    age_h = _TOKEN_STORE.token_age_hours()
    expires_in = _TOKEN_STORE.effective_expires_in_hours()
    if expires_in is None and age_h is not None:
        expires_in = max(0.0, 24.0 - age_h)
    now = datetime.now(_IST).strftime("%d-%b-%Y %H:%M:%S IST")

    if tok and expires_in is not None and expires_in > 0:
        broker_status = "🟢 Connected"
        broker_health = "Healthy"
    elif tok:
        broker_status = "🔴 Expired Token"
        broker_health = "Token Expired"
    else:
        broker_status = "🔴 Disconnected"
        broker_health = "No Token"

    token_age_line = f"{age_h:.1f} hours" if age_h is not None else "N/A"
    token_expires_line = f"{expires_in:.1f} hours" if expires_in is not None and tok else "N/A"
    saved_at_line = saved_at.strftime("%d-%b %H:%M IST") if saved_at else "N/A"
    jwt_exp = _TOKEN_STORE.jwt_expires_at_local()
    jwt_exp_line = jwt_exp.strftime("%d-%b %H:%M %Z") if jwt_exp else "N/A"
    feed_block = format_feed_health_block(app)
    uptime = app.bot_data.get("started_at_ist", "Active") if app else "Active"
    try:
        proc = classify_bot("drishti")
        if proc.state is BotRunState.RUNNING:
            python_line = "🟢 Running"
        elif proc.state is BotRunState.STOPPED:
            python_line = "🔴 Stopped"
        else:
            python_line = f"🟠 {proc.state.value}"
        if proc.warnings:
            python_line += f" — {proc.warnings[0]}"
    except Exception as exc:
        python_line = f"🟠 Unknown ({html.escape(str(exc))})"

    return (
        "📡 <b>System Health Report</b>\n\n"
        f"🕒 <b>Timestamp:</b> {html.escape(now)}\n\n"
        "🔌 <b>Broker Connection</b>\n"
        f"  Status: {broker_status}\n"
        f"  Health: {html.escape(broker_health)}\n\n"
        "🔑 <b>Token Information</b>\n"
        f"  Age:        {html.escape(token_age_line)}\n"
        f"  Expires in: {html.escape(token_expires_line)}\n"
        f"  JWT exp:    {html.escape(jwt_exp_line)}\n"
        f"  Saved at:   {html.escape(saved_at_line)}\n\n"
        "📈 <b>NIFTY LTP Feed</b>\n"
        f"{feed_block}\n\n"
        "⚙️ <b>System Status</b>\n"
        f"  Python Process: {python_line}\n"
        f"  Uptime:         {html.escape(str(uptime))}\n\n"
        "💡 <b>Quick Action:</b> Tap <b>Update Token</b> to refresh"
    )


def _require_message(update: Update) -> Message:
    message = update.message
    if message is None:
        raise ValueError("Telegram update is missing a message")
    return message


def _require_query(update: Update) -> CallbackQuery:
    query = update.callback_query
    if query is None:
        raise ValueError("Telegram update is missing a callback query")
    return query


def _remember_chat_id(update: Update) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    try:
        from core.telegram_credentials import upsert_bot_credential_key

        path = upsert_bot_credential_key("drishti", "CHAT_ID", str(chat.id))
        logger.info("DRISHTI chat id remembered in %s: %s", path, chat.id)
        # Best-effort legacy mirror for older tooling
        if _DRISHTI_TOKEN_ENV.is_file():
            text = _DRISHTI_TOKEN_ENV.read_text(encoding="utf-8")
            line = f"DRISHTI_CHAT_ID={chat.id}"
            if "DRISHTI_CHAT_ID=" in text:
                lines = [
                    line if item.startswith("DRISHTI_CHAT_ID=") else item
                    for item in text.splitlines()
                ]
                text = chr(10).join(lines) + chr(10)
            else:
                text = text.rstrip() + chr(10) + line + chr(10)
            _DRISHTI_TOKEN_ENV.write_text(text, encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not remember DRISHTI chat id: %s", exc)



def _fleet_keyboard() -> InlineKeyboardMarkup:
    """Enhanced fleet keyboard with categorized sections and visual icons.

    Phase 1: not exposed in UI — kept for future fleet dashboard restore.
    """
    rows = [
        # Header
        [InlineKeyboardButton("┌───── 🤖 BOTS ─────┐", callback_data="header_bots")],
        # Bots section
        [
            InlineKeyboardButton("👁 DRISHTI", callback_data=f"{_CB_FLEET}:drishti"),
            InlineKeyboardButton("🛡 KAVACH", callback_data=f"{_CB_FLEET}:kavach"),
        ],
        [
            InlineKeyboardButton("💰 LAKSHMI", callback_data=f"{_CB_FLEET}:lakshmi"),
        ],
        # Modules header
        [InlineKeyboardButton("└─── ⚙️ MODULES ───┘", callback_data="header_modules")],
        # Protection modules
        [
            InlineKeyboardButton("🔒 ATO Protection", callback_data=f"{_CB_FLEET}:ato_protection"),
            InlineKeyboardButton(
                "📈 Profit Trailing", callback_data=f"{_CB_FLEET}:profit_trailing"
            ),
        ],
        [
            InlineKeyboardButton(
                "🌙 Overnight Hedge", callback_data=f"{_CB_FLEET}:overnight_hedge"
            ),
            InlineKeyboardButton(
                "📊 Position Monitor", callback_data=f"{_CB_FLEET}:position_monitor"
            ),
        ],
        [
            InlineKeyboardButton("🚨 Emergency Exit", callback_data=f"{_CB_FLEET}:emergency_exit"),
        ],
        # Navigation
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=f"{_CB_MENU}:main")],
    ]
    return InlineKeyboardMarkup(rows)


def _main_menu_keyboard(application: Application | None = None) -> InlineKeyboardMarkup:
    """Primary DRISHTI actions — UAT-aware layout (buttons only, no commands)."""
    uat_on = is_uat_market_replay_running(application)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("🩺 Drishti Status", callback_data=f"{_CB_MENU}:health"),
            InlineKeyboardButton("🔑 Token Status", callback_data=f"{_CB_MENU}:status"),
        ],
        [
            InlineKeyboardButton("📈 Nifty LTP", callback_data=f"{_CB_MENU}:nifty_ltp"),
            InlineKeyboardButton(
                "⚙️ LTP Feed Setup", callback_data=f"{feed_callback_prefix()}:setup"
            ),
        ],
    ]
    if uat_on:
        rows.append(
            [
                InlineKeyboardButton(
                    "🧪 UAT Dashboard", callback_data=f"{_CB_MENU}:uat_dashboard"
                ),
                InlineKeyboardButton("⏩ Replay Speed", callback_data=f"{_CB_MENU}:uat_speed"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "🚫 Deactivate Token", callback_data=f"{_CB_MENU}:deactivate_token"
            ),
            InlineKeyboardButton("🔄 Update Token", callback_data=f"{_CB_MENU}:update_token"),
        ]
    )
    return InlineKeyboardMarkup(rows)


async def _send_alive_menu(message: Message, application: Application | None = None) -> None:
    """Post-token / liveness card with timestamp and action buttons."""
    now = datetime.now(_IST).strftime("%d-%b-%Y %H:%M:%S IST")
    feed_line = format_feed_status_line(application)
    status_block = feed_line
    expires_in = _TOKEN_STORE.effective_expires_in_hours()
    token_hint = ""
    if _TOKEN_STORE.is_expired():
        token_hint = (
            "\n\n🟠 <b>Token expired</b> — tap <b>Update Token</b>. "
            "Live NIFTY feed cannot start until refreshed."
        )
    elif expires_in is not None and 0 < expires_in <= 4:
        token_hint = f"\n\n🟠 <b>Token expires in {expires_in:.1f}h</b> — consider Update Token"

    uat_banner = ""
    if is_uat_market_replay_running(application):
        from bat_telegram.bots.drishti.nifty_feed_integration import get_uat_replay_progress
        from core.nifty_ltp_feed import read_nifty_ltp_cache
        from core.nifty_ltp_uat_replay import format_uat_time_block

        progress = get_uat_replay_progress(application)
        if progress is not None:
            uat_banner = (
                "\n\n<b>[DRISHTI UAT]</b>\n"
                f"<b>Nifty LTP:</b> ₹{progress.ltp:,.2f}\n"
                f"<code>{html.escape(format_uat_time_block(progress))}</code>"
            )
        else:
            snap = read_nifty_ltp_cache()
            ltp_line = f"₹{snap.ltp:,.2f}" if snap and snap.ltp > 0 else "warming…"
            uat_banner = (
                "\n\n<b>[DRISHTI UAT] Market Replay · evening session</b>\n"
                f"Nifty LTP  <b>{ltp_line}</b>\n"
                "<i>Tap <b>UAT Dashboard</b> or <b>Nifty LTP</b> — no commands needed.</i>"
            )

    from bat_telegram.alive_branding import reply_alive_card

    await reply_alive_card(
        message,
        f"🟢 <b>DRISHTI ACTIVE</b>\n<code>{html.escape(now)}</code>\n\n"
        f"{status_block}{uat_banner}{token_hint}",
        reply_markup=_main_menu_keyboard(application),
        bot_name="drishti",
    )


def _upcoming_schedule(target: str, params: dict[str, Any]) -> str:
    if target == "drishti":
        times = params.get("token_reminders", {}).get("times_ist", ["09:00", "15:30", "23:00"])
        return f"Token reminders: {', '.join(times)} | Health: hourly in market hours"
    if target == "kavach":
        return "Command-driven deploy/ATO control"
    if target == "lakshmi":
        eod_time = params.get("eod_summary", {}).get("time_ist", "15:35")
        return f"EOD summary: {eod_time} IST | MTM alerts live"
    if target == "ato_protection":
        return "Market hours when deployment is confirmed"
    if target == "profit_trailing":
        return "0DTE only when deployment is confirmed"
    if target == "overnight_hedge":
        return "Post-16:00 on eligible sessions"
    if target == "position_monitor":
        return "Always-on polling"
    if target == "emergency_exit":
        return "Always-on command responder"
    return "N/A"


def _render_fleet_status(context: ContextTypes.DEFAULT_TYPE, target: str) -> str:
    """Enhanced fleet status with visual formatting and detailed information."""
    apps = context.bot_data.get("apps", {})
    modules = context.bot_data.get("modules", {})
    params = context.bot_data.get("params", {})
    now = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S IST")

    if target in apps:
        app = apps[target]
        is_active = bool(app.bot_data.get("started_at_ist"))
        active_since = app.bot_data.get("started_at_ist", "unknown")
        last_deactivated = app.bot_data.get("last_stopped_at_ist", "not recorded")
        last_heartbeat = app.bot_data.get("last_heartbeat_ist", active_since)
        latest_error = app.bot_data.get("latest_error", "none")
        schedule = _upcoming_schedule(target, app.bot_data.get("params", params))
        entity_type = "BOT"
    else:
        module = modules.get(target)
        if module is None:
            return (
                "┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "┃  ⚠️ <b>Status Unavailable</b>  ┃\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
                f"Fleet status unavailable for: <b>{target}</b>"
            )
        is_active = getattr(module, "is_running", False)
        active_since = now if is_active else "not recorded"
        last_deactivated = "not recorded"
        last_heartbeat = now if is_active else "not running"
        latest_error = getattr(module, "_error", None) or "none"
        schedule = _upcoming_schedule(target, params)
        entity_type = "MODULE"

    # Status indicators
    status_icon = "🟢" if is_active else "🔴"
    status_text = "ACTIVE" if is_active else "INACTIVE"
    error_icon = "✅" if latest_error == "none" else "⚠️"

    # Get appropriate icon for entity
    entity_icons = {
        "drishti": "👁",
        "kavach": "🛡",
        "lakshmi": "💰",
        "ato_protection": "🔒",
        "profit_trailing": "📈",
        "overnight_hedge": "🌙",
        "position_monitor": "📊",
        "emergency_exit": "🚨",
    }
    entity_icon = entity_icons.get(target, "⚙️")

    return (
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  {entity_icon} <b>{target.upper()}</b> {entity_type}\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"🟢 <b>Status:</b> {status_icon} {status_text}\n\n"
        "╔══════════════════════════════════╗\n"
        "║  🕒 <b>Timeline</b>                  ║\n"
        "╚══════════════════════════════════╝\n"
        f"  Active since:     {active_since}\n"
        f"  Last deactivated: {last_deactivated}\n"
        f"  Last heartbeat:   {last_heartbeat}\n\n"
        "╔══════════════════════════════════╗\n"
        "║  📅 <b>Schedule</b>                  ║\n"
        "╚══════════════════════════════════╝\n"
        f"  {schedule}\n\n"
        "╔══════════════════════════════════╗\n"
        "║  🛠 <b>Diagnostics</b>               ║\n"
        "╚══════════════════════════════════╝\n"
        f"  Latest error: {error_icon} {latest_error}"
    )


def _gift_probe_symbols(params: dict[str, Any]) -> list[str]:
    """Return ordered symbols to probe for GIFT Nifty LTP.

    Exchange naming can vary by data source, so we probe a small ordered list.
    Override via drishti params: token_validation.gift_probe_symbols.
    """
    default_symbols = ["GIFT NIFTY", "GIFTNIFTY", "NIFTY GIFT"]
    configured = params.get("token_validation", {}).get("gift_probe_symbols")
    if configured is None:
        configured = params.get("gift_nifty", {}).get("symbol_candidates", default_symbols)
    if not isinstance(configured, list):
        return default_symbols
    cleaned = [str(s).strip() for s in configured if str(s).strip()]
    return cleaned or default_symbols


def _fetch_gift_ltp(broker, probe_symbols: list[str]) -> tuple[str, float]:
    """Fetch GIFT Nifty LTP by probing candidate symbols.

    Returns (resolved_symbol, ltp) once any symbol resolves with a positive LTP.
    """
    errors: list[str] = []
    for symbol in probe_symbols:
        try:
            data = broker.get_ltp([symbol])
            ltp_raw = data.get(symbol)
            if ltp_raw is None:
                errors.append(f"{symbol}: missing")
                continue
            ltp = float(ltp_raw)
            if ltp <= 0:
                errors.append(f"{symbol}: non-positive {ltp}")
                continue
            return symbol, ltp
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    raise RuntimeError("GIFT LTP fetch failed for all symbols: " + " | ".join(errors))


async def _get_client_code(context: ContextTypes.DEFAULT_TYPE) -> str:
    client_code = context.bot_data.get("client_code", "")
    if client_code:
        return client_code

    from dotenv import load_dotenv

    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / "config" / ".env")
    return os.environ.get("DHAN_CLIENT_CODE", "").strip()


async def _resolve_broker(context: ContextTypes.DEFAULT_TYPE):
    """Return live broker from bot_data, or create one from persisted token."""
    broker = context.bot_data.get("broker")
    if broker is not None:
        return broker

    tok, _ = _TOKEN_STORE.load()
    if not tok or _TOKEN_STORE.is_expired():
        return None

    client_code = await _get_client_code(context)
    if not client_code:
        return None

    from core.broker import BatmanBroker

    broker = await asyncio.to_thread(BatmanBroker.connect_with_token, client_code, tok)
    context.bot_data["broker"] = broker
    context.bot_data.setdefault("client_code", client_code)
    return broker


async def _reply_nifty_ltp(message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_nifty_ltp_from_cache(
        message,
        context,
        token_store=_TOKEN_STORE,
        main_menu_keyboard=_main_menu_keyboard(context.application),
        format_ltp_card=_format_nifty_ltp_card,
    )


async def _reply_live_price(message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_live_price(
        message,
        context,
        token_store=_TOKEN_STORE,
        main_menu_keyboard=_main_menu_keyboard(context.application),
        format_ltp_card=_format_nifty_ltp_card,
    )


async def _reply_gift_nifty(message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_gift_nifty_ltp(
        message,
        context,
        token_store=_TOKEN_STORE,
        main_menu_keyboard=_main_menu_keyboard(context.application),
        format_ltp_card=_format_nifty_ltp_card,
    )


async def _process_token(
    update: Update,
    token: str,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    broker=None,
    client_code: str = "",
    params: dict[str, Any] | None = None,
) -> None:
    """Validate token with live NIFTY LTP before saving — money-safe path."""
    from core.exceptions import BrokerAuthError, BrokerConnectionError
    from core.nifty_ltp import fetch_nifty_ltp, validate_dhan_access_token

    _set_awaiting_token(context, False)
    message = _require_message(update)

    if context is not None and not client_code:
        client_code = await _get_client_code(context)

    await message.reply_text(
        "⏳ Validating token with live NIFTY check…", parse_mode=ParseMode.HTML
    )

    if not client_code:
        await message.reply_text(
            "🔴 <b>Setup incomplete</b>\n\nAdd <code>DHAN_CLIENT_CODE</code> to <code>config/.env</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        return

    ok, auth_error = await asyncio.to_thread(validate_dhan_access_token, client_code, token)
    if not ok:
        await message.reply_text(
            "🔴 <b>Token rejected by Dhan</b>\n\n"
            f"<code>{html.escape(auth_error)}</code>\n\n"
            "Nothing was saved. Paste a fresh JWT from Dhan web.",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        return

    try:
        ltp, source = await fetch_nifty_ltp(client_code, token)
    except (BrokerAuthError, BrokerConnectionError) as exc:
        logger.error("Token validation LTP failed: %s", exc)
        await publish_incident(
            source="drishti",
            scenario="token_update_failure",
            severity="critical",
            category="connectivity",
            title="Token validation failed — LTP not confirmed",
            error_message=str(exc),
            next_action="Send a fresh Dhan JWT with Data API enabled.",
            source_bot=message.get_bot(),
            source_chat_id=str(update.effective_chat.id) if update.effective_chat else None,
            send_to_source=False,
        )
        await message.reply_text(
            "🔴 <b>Token not saved</b>\n\n"
            f"<code>{html.escape(str(exc))}</code>\n\n"
            "Fix Dhan Data API subscription or paste a fresh JWT.",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        return

    _TOKEN_STORE.save(token)
    if context is not None:
        context.bot_data.pop("broker", None)

    from core.bot_logging import bot_nifty_ltp_log_dir
    from core.nifty_ltp_feed import append_nifty_ltp_audit_log, seed_nifty_ltp_cache

    _root = Path(__file__).resolve().parents[3]
    params = (context.bot_data.get("params") or {}) if context is not None else (params or {})
    poll_s = int(params.get("nifty_ltp_poll_interval_seconds", 2))
    seed_nifty_ltp_cache(ltp, feed_healthy=True, poll_interval_seconds=poll_s)
    await asyncio.to_thread(
        append_nifty_ltp_audit_log,
        bot_nifty_ltp_log_dir(_root),
        datetime.now(_IST),
        ltp,
        source,
        event="token_save",
    )

    broker_connected = False
    if broker and client_code:
        try:
            await asyncio.to_thread(broker.hot_reload_token, client_code, token)
            broker_connected = True
        except Exception as exc:
            logger.warning("Broker hot-reload after token save failed: %s", exc)
    elif context is not None:
        try:
            from core.broker import BatmanBroker

            new_broker = await asyncio.to_thread(
                BatmanBroker.connect_with_token, client_code, token
            )
            context.bot_data["broker"] = new_broker
            context.bot_data.setdefault("client_code", client_code)
            broker_connected = True
        except Exception as exc:
            logger.warning("Broker connect after token save failed: %s", exc)

    verify_lines = "✅ <b>Token saved & verified</b>\n\n" + _format_nifty_ltp_card(ltp, source)
    if not broker_connected:
        verify_lines += (
            "\n\n⚠️ <b>Broker reconnect pending</b>\n"
            "Token is on disk. KAVACH will pick it up via token watch, "
            "or restart KAVACH after DRISHTI saves."
        )

    await message.reply_text(
        verify_lines,
        parse_mode=ParseMode.HTML,
    )

    if context is not None:
        params = context.bot_data.get("params") or {}
        _, created = ensure_default_feed_config(params)
        restart_nifty_feed(context.application, _TOKEN_STORE)
        if created:
            await message.reply_text(
                "⚙️ <b>LTP feed auto-started</b>\n\n"
                "Default REST poller is running (2s poll, 10s stale alert).\n"
                "Tune via <b>LTP Feed Setup</b> anytime.",
                parse_mode=ParseMode.HTML,
            )

    await _send_alive_menu(message, context.application if context else None)


# ═══════════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════════


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    await message.reply_text(
        "👁 *DRISHTI — Infrastructure & Token Bot*\n\n"
        "I manage your Dhan access token and watch broker health.\n\n"
        "*Commands:*\n"
        "/update\\_token      — Send me a fresh Dhan JWT token\n"
        "/deactivate\\_token  — Revoke the current token immediately\n"
        "/status            — Token age & expiry countdown\n"
        "/health            — Full system health report\n"
        "/ping              — Liveness check\n\n"
        "_Or just paste your JWT token directly at any time._",
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    now = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
    await message.reply_text(f"🟢 DRISHTI alive. {now} IST")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    tok, _ = _TOKEN_STORE.load()
    if not tok:
        await message.reply_text(
            "🔴 No token stored.\n\n" "Run /update_token to connect the broker."
        )
        return
    await message.reply_text(f"🔍 *Token Status*\n\n{_token_summary()}")


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    tok, _ = _TOKEN_STORE.load()
    age_h = _TOKEN_STORE.token_age_hours()
    now = datetime.now().strftime("%H:%M:%S")

    broker_line = "✅ Connected" if tok else "🔴 No token"
    token_age_line = f"{age_h:.1f} h" if age_h is not None else "N/A"

    await message.reply_text(
        f"🔍 *System Health* — {now} IST\n\n"
        f"Broker  : {broker_line}\n"
        f"Token   : {token_age_line} old\n\n"
        f"_Use /update\\_token to refresh the Dhan JWT._",
    )


async def cmd_fleet_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    await message.reply_text(
        "Select a bot or module to inspect:",
        reply_markup=_fleet_keyboard(),
    )


async def cmd_update_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proactively ask the user to paste a fresh Dhan JWT token."""
    _remember_chat_id(update)
    if not await guard_paused_command(
        update,
        context,
        bot_name="drishti",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return
    _set_awaiting_token(context, True)
    message = _require_message(update)

    tok, _ = _TOKEN_STORE.load()
    age_h = _TOKEN_STORE.token_age_hours()
    current_info = (
        f"Current token: {age_h:.1f} h old"
        if tok and age_h is not None
        else "No token currently stored"
    )

    await message.reply_text(
        f"🔄 *Update Dhan Access Token*\n\n"
        f"{current_info}\n\n"
        f"Please paste your fresh Dhan JWT access token now\\.\n"
        f"_Get it from: web\\.dhan\\.co → Profile → Access DhanHQ APIs_",
    )


async def cmd_deactivate_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke the current token — clears token store and disconnects broker."""
    if not await guard_paused_command(
        update,
        context,
        bot_name="drishti",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return
    _set_awaiting_token(context, False)
    message = _require_message(update)

    tok, saved_at = _TOKEN_STORE.load()
    if not tok:
        await message.reply_text(
            "ℹ️ No active token to deactivate.\n\n" "Run /update_token when you want to connect."
        )
        return

    # Confirm with inline keyboard before wiping
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, deactivate", callback_data="deactivate_confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="deactivate_cancel"),
            ]
        ]
    )
    saved_fmt = saved_at.strftime("%d-%b %H:%M") if saved_at else "unknown"
    await message.reply_text(
        f"⚠️ *Deactivate token?*\n\n"
        f"Token saved at: {saved_fmt} IST\n"
        f"Age: {(_TOKEN_STORE.token_age_hours() or 0):.1f} h\n\n"
        f"This will disconnect the broker\\. Batman will stop trading until you supply a new token via /update\\_token\\.",
        reply_markup=keyboard,
    )


async def on_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Yes/No inline keyboard from the interactive TYPE 1 token reminder."""
    query = _require_query(update)
    await query.answer()

    if query.data == "reminder_yes":
        _set_awaiting_token(context, True)
        await query.edit_message_text(
            "🔑 Paste your Dhan JWT in this chat now.",
        )
    else:  # reminder_no or timeout
        await query.edit_message_text(
            "✅ OK — I'll remind you at the next scheduled time\\.",
        )


async def on_deactivate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Yes/Cancel inline keyboard for /deactivate_token."""
    query = _require_query(update)
    await query.answer()

    if query.data == "deactivate_confirm":
        _TOKEN_STORE.clear()
        deactivate_ltp_feed(context.application)
        context.bot_data.pop("broker", None)
        logger.warning("DRISHTI: access token deactivated by user")
        await query.edit_message_text(
            "🔴 *Token deactivated.*\n\n"
            "Broker is now disconnected\\.\n"
            "Run /update\\_token to reconnect when you have a fresh Dhan JWT\\.",
        )
    else:
        await query.edit_message_text("✅ Cancelled — token remains active.")


async def on_fleet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _require_query(update)
    await query.answer()
    target = (query.data or "").split(":", 1)[-1]
    await query.edit_message_text(
        _render_fleet_status(context, target),
        reply_markup=_fleet_keyboard(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Message handler — JWT token paste (proactive or via /update_token flow)
# ═══════════════════════════════════════════════════════════════════════════════


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any plain text that isn't a command.

    Cases handled:
      1. Per-chat awaiting flag  → any non-command text = token
      2. Text looks like a JWT    → treat as token regardless
      3. "hello" / "hi"           → show full command list
      4. Anything else            → "invalid command" + command list
    """
    _remember_chat_id(update)
    message = _require_message(update)

    text = (message.text or "").strip()
    if not text:
        return

    _HELP = (
        "🔍 *DRISHTI — Available Commands*\n\n"
        "/update\\_token      — Paste a fresh Dhan JWT token\n"
        "/deactivate\\_token  — Revoke current token & disconnect broker\n"
        "/status            — Token age & expiry countdown\n"
        "/health            — Full system health check\n"
        "/ping              — Liveness check\n\n"
        "_Or paste your JWT token directly at any time\\._"
    )

    # Waiting state: accept any non-command text as the token
    if _is_awaiting_token(context) and not text.startswith("/"):
        broker = context.bot_data.get("broker")
        client_code = context.bot_data.get("client_code", "")
        await _process_token(
            update,
            text,
            context=context,
            broker=broker,
            client_code=client_code,
            params=context.bot_data.get("params", {}),
        )
        return

    # Auto-detect JWT paste even without /update_token
    if _is_jwt(text):
        broker = context.bot_data.get("broker")
        client_code = context.bot_data.get("client_code", "")
        await _process_token(
            update,
            text,
            broker=broker,
            client_code=client_code,
            params=context.bot_data.get("params", {}),
        )
        return

    # Hello / help
    if text.lower() in ("hello", "hi"):
        await message.reply_text(
            "👁 Hello\\! I'm *DRISHTI*, your infrastructure & token bot\\.\n\n" + _HELP,
        )
        return

    # Unknown command or free text
    prefix = f"❌ Unknown: `{text}`\n\n" if text.startswith("/") else ""
    await message.reply_text(
        prefix + _HELP,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Bot builder — called from main.py
# ═══════════════════════════════════════════════════════════════════════════════


async def pretty_cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    await _send_alive_menu(message, context.application)


async def pretty_cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    await _send_alive_menu(message, context.application)


async def pretty_cmd_nifty_ltp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    await _reply_nifty_ltp(_require_message(update), context)


async def pretty_cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    tok, _ = _TOKEN_STORE.load()
    if not tok:
        await message.reply_text(
            "🔴 <b>No Dhan token stored</b>\n\n"
            "Run <code>/update_token</code> and paste a fresh access token.",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        return
    await message.reply_text(
        _token_summary(),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def pretty_cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    await message.reply_text(
        _build_health_report_html(context.application),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def pretty_cmd_nifty_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    await message.reply_text(
        format_nifty_status_html(context.application),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def pretty_cmd_fleet_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    await message.reply_text(
        "🛰 <b>Fleet Status</b>\nSelect a bot or module to inspect:",
        parse_mode=ParseMode.HTML,
        reply_markup=_fleet_keyboard(),
    )


async def pretty_cmd_update_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    if not await guard_paused_command(
        update,
        context,
        bot_name="drishti",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return

    _set_awaiting_token(context, True)
    message = _require_message(update)

    await message.reply_text(
        "🔑 Paste your Dhan JWT in this chat now.",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def pretty_cmd_deactivate_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    if not await guard_paused_command(
        update,
        context,
        bot_name="drishti",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return

    _set_awaiting_token(context, False)
    message = _require_message(update)
    tok, saved_at = _TOKEN_STORE.load()
    if not tok:
        await message.reply_text(
            "ℹ️ <b>No active token</b>\n\n"
            "Run <code>/update_token</code> when you want to connect.",
            parse_mode=ParseMode.HTML,
        )
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes, deactivate", callback_data="pretty_deactivate_confirm"
                ),
                InlineKeyboardButton("Cancel", callback_data="pretty_deactivate_cancel"),
            ]
        ]
    )
    saved_fmt = saved_at.strftime("%d-%b %H:%M IST") if saved_at else "unknown"
    await message.reply_text(
        "⚠️ <b>Deactivate token?</b>\n\n"
        f"Saved at: <code>{html.escape(saved_fmt)}</code>\n"
        f"Age: <code>{(_TOKEN_STORE.token_age_hours() or 0):.1f} h</code>\n\n"
        "Batman will stay disconnected until you provide a fresh token.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def pretty_on_deactivate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _require_query(update)
    await query.answer()

    if query.data == "pretty_deactivate_confirm":
        _TOKEN_STORE.clear()
        deactivate_ltp_feed(context.application)
        context.bot_data.pop("broker", None)
        logger.warning("DRISHTI: access token deactivated by user")
        await query.edit_message_text(
            "🔴 <b>Token deactivated</b>\n\n"
            "Broker is disconnected. Run <code>/update_token</code> to reconnect.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await query.edit_message_text("✅ Cancelled. Token remains active.")


async def _on_handler_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Telegram handler failures and return operator to the alive menu."""
    logger.error("DRISHTI handler error", exc_info=context.error)
    if not isinstance(update, Update):
        return
    message = update.effective_message
    if message is None:
        return
    try:
        await message.reply_text(
            "⚠️ <b>Something went wrong.</b> Tap <b>Health</b> or send /start again.",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
    except Exception:
        pass


async def pretty_on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    query = _require_query(update)
    await query.answer()

    message = query.message
    if message is None:
        return

    action = (query.data or "").split(":", 1)[-1]

    if action in {"dashboard", "help", "main"}:
        await _send_alive_menu(message, context.application)
        return

    if action == "ping":
        await _send_alive_menu(message, context.application)
        return

    if action == "status":
        tok, _ = _TOKEN_STORE.load()
        if not tok:
            await message.reply_text(
                "🔴 <b>No Dhan token stored</b>\n\n"
                "Tap <b>Update Token</b> and paste a fresh access token.",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_keyboard(),
            )
            return
        await message.reply_text(
            _token_summary(),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        return

    if action == "health":
        await message.reply_text(
            _build_health_report_html(context.application),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        return

    if action == "update_token":
        _set_awaiting_token(context, True)
        await message.reply_text(
            "🔑 Paste your Dhan JWT in this chat now.",
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        return

    if action == "deactivate_token":
        tok, saved_at = _TOKEN_STORE.load()
        if not tok:
            await message.reply_text(
                "ℹ️ <b>No active token</b>\n\n" "Tap <b>Update Token</b> when you want to connect.",
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_keyboard(),
            )
            return

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Yes, deactivate", callback_data="pretty_deactivate_confirm"
                    ),
                    InlineKeyboardButton("Cancel", callback_data="pretty_deactivate_cancel"),
                ]
            ]
        )
        saved_fmt = saved_at.strftime("%d-%b %H:%M IST") if saved_at else "unknown"
        await message.reply_text(
            "⚠️ <b>Deactivate token?</b>\n\n"
            f"Saved at: <code>{html.escape(saved_fmt)}</code>\n"
            f"Age: <code>{(_TOKEN_STORE.token_age_hours() or 0):.1f} h</code>\n\n"
            "Batman will stay disconnected until you provide a fresh token.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return

    # Phase 1: Fleet menu disabled — handlers kept below for future restore.
    # if action == "fleet_status":
    #     await message.reply_text(
    #         "🛰 <b>Fleet Status</b>\nSelect a bot or module to inspect:",
    #         parse_mode=ParseMode.HTML,
    #         reply_markup=_fleet_keyboard(),
    #     )
    #     return

    if action == "nifty_ltp":
        await _reply_nifty_ltp(message, context)
        return

    if action == "uat_dashboard":
        await message.reply_text(
            format_uat_dashboard_html(context.application),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(context.application),
        )
        return

    if action == "uat_speed":
        await message.reply_text(
            "<b>[DRISHTI UAT] Replay Speed</b>\n\n"
            "Choose how fast stored ticks are replayed:",
            parse_mode=ParseMode.HTML,
            reply_markup=uat_speed_keyboard(),
        )
        return

    if action == "nifty_status":
        await message.reply_text(
            format_nifty_status_html(context.application),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(context.application),
        )
        return

    if action == "live_price":
        await _reply_live_price(message, context)
        return

    if action == "gift_nifty":
        await _reply_gift_nifty(message, context)
        return

    await _send_alive_menu(message, context.application)


async def _alive_menu_with_context(message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_alive_menu(message, context.application)


async def pretty_on_feed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    await on_feed_setup_callback(
        update,
        context,
        token_store=_TOKEN_STORE,
        main_menu_keyboard=_main_menu_keyboard(context.application),
        send_alive_menu=_alive_menu_with_context,
    )


async def pretty_on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_chat_id(update)
    message = _require_message(update)
    text = (message.text or "").strip()
    if not text:
        return

    if _is_awaiting_token(context) and not text.startswith("/"):
        await _process_token(
            update,
            text,
            context=context,
            broker=context.bot_data.get("broker"),
            client_code=context.bot_data.get("client_code", ""),
            params=context.bot_data.get("params", {}),
        )
        return

    if _is_jwt(text):
        await _process_token(
            update,
            text,
            context=context,
            broker=context.bot_data.get("broker"),
            client_code=context.bot_data.get("client_code", ""),
            params=context.bot_data.get("params", {}),
        )
        return

    await _send_alive_menu(message, context.application)


def build_application(
    broker=None,
    client_code: str = "",
    state=None,
    event_bus=None,
) -> Application:
    """Build and return the DRISHTI PTB Application.

    Pass *broker* and *client_code* so the token hot-reload can reach the live
    BatmanBroker instance.  *state* and *event_bus* are stored in ``bot_data``
    for use by background coroutines.

    Background coroutines are wired via ``post_init`` (→ _drishti_post_init):
      _reminder_scheduler_loop  — TYPE 1 scheduled token reminders
      _token_age_monitor_loop   — stale JWT warnings
      feed_watchdog_loop        — REST LTP poller auto-restart

    Usage (from main.py)::

        app = build_application(broker=broker, client_code=cfg.client_code,
                                state=state, event_bus=bus)
        await app.initialize()   # triggers post_init → starts background tasks
        await app.start()
        await app.updater.start_polling()
    """
    cfg = load_bot_config("drishti")

    app = (
        Application.builder()
        .token(cfg.bot_token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(60.0)
        .media_write_timeout(60.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(30.0)
        .get_updates_write_timeout(30.0)
        .post_init(_drishti_post_init)
        .concurrent_updates(True)
        .build()
    )

    # Inject shared objects into bot_data (accessible in all handlers)
    app.bot_data["broker"] = broker
    app.bot_data["client_code"] = client_code
    app.bot_data["chat_id"] = cfg.chat_id
    app.bot_data["state"] = state
    app.bot_data["event_bus"] = event_bus
    app.bot_data["params"] = cfg.params

    # ── Register handlers ──────────────────────────────────────
    try:
        from bat_telegram.update_audit import attach_update_audit
        attach_update_audit(app)
    except Exception as _audit_exc:
        logging.getLogger(__name__).warning("update audit attach failed: %s", _audit_exc)
    
    app.add_handler(CommandHandler("start", pretty_cmd_start))
    app.add_handler(CommandHandler("ping", pretty_cmd_ping))
    app.add_handler(CommandHandler("status", pretty_cmd_status))
    app.add_handler(CommandHandler("health", pretty_cmd_health))
    app.add_handler(CommandHandler("niftystatus", pretty_cmd_nifty_status))
    # Phase 1: Fleet disabled — uncomment to restore /fleet_status:
    # app.add_handler(CommandHandler("fleet_status", pretty_cmd_fleet_status))
    app.add_handler(CommandHandler("nifty_ltp", pretty_cmd_nifty_ltp))
    app.add_handler(CommandHandler("update_token", pretty_cmd_update_token))
    app.add_handler(CommandHandler("deactivate_token", pretty_cmd_deactivate_token))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(on_reminder_callback, pattern="^reminder_"))
    app.add_handler(CallbackQueryHandler(pretty_on_menu_callback, pattern=f"^{_CB_MENU}:"))
    app.add_handler(
        CallbackQueryHandler(pretty_on_feed_callback, pattern=f"^{feed_callback_prefix()}:")
    )
    app.add_handler(
        CallbackQueryHandler(pretty_on_deactivate_callback, pattern="^pretty_deactivate_")
    )
    app.add_handler(CallbackQueryHandler(on_deactivate_callback, pattern="^deactivate_"))
    # Phase 1: Fleet disabled — uncomment to restore fleet target callbacks:
    # app.add_handler(CallbackQueryHandler(on_fleet_callback, pattern=f"^{_CB_FLEET}:"))

    # Plain text → token paste handler (lowest priority)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pretty_on_message))

    app.add_error_handler(_on_handler_error)
    app.post_stop = cleanup_managed_runtime

    logger.info("DRISHTI bot application built ✓")
    return app


# ═══════════════════════════════════════════════════════════════════════════════
# Background coroutines (started via post_init — run for the life of the process)
# ═══════════════════════════════════════════════════════════════════════════════


async def _reminder_scheduler_loop(app: Application) -> None:
    """TYPE 1 — scheduled token reminder at 09:00, 15:30, 23:00 IST on weekdays.

    Suppressed when token is still valid outside the expiry warning window.
    Respects quiet hours (08:00–23:30 IST).
    """
    params = app.bot_data.get("params", {}) or {}
    reminder_cfg = params.get("token_reminders") or {}
    reminder_times = reminder_cfg.get("times_ist", ["09:00", "15:30", "23:00"])
    warning_minutes = int((params.get("alerts") or {}).get("token_expiry_warning_minutes", 60))
    skip_holidays = bool(reminder_cfg.get("skip_nse_holidays", True))
    chat_id = app.bot_data.get("chat_id", "")

    while True:
        await asyncio.sleep(60)
        try:
            now_ist = datetime.now(_IST)

            if now_ist.weekday() >= 5 and reminder_cfg.get("only_on_weekdays", True):
                continue

            if skip_holidays:
                from core.utils import is_trading_day

                if not is_trading_day(now_ist.date()):
                    continue

            t = now_ist.time().replace(second=0, microsecond=0)
            if not (_QUIET_START <= t <= _QUIET_END):
                continue

            time_str = now_ist.strftime("%H:%M")
            if time_str not in reminder_times:
                continue

            reminder_key = f"{now_ist.date().isoformat()}:{time_str}"
            if app.bot_data.get("last_type1_reminder_key") == reminder_key:
                continue

            tok, _ = _TOKEN_STORE.load()
            expires_in = _TOKEN_STORE.effective_expires_in_hours()
            if not should_send_type1_token_reminder(
                has_token=bool(tok),
                expires_in_hours=expires_in,
                warning_minutes=warning_minutes,
            ):
                logger.debug("TYPE 1 reminder suppressed at %s IST — token valid", time_str)
                app.bot_data["last_type1_reminder_key"] = reminder_key
                continue

            age_h = _TOKEN_STORE.token_age_hours()
            token_state = (
                f"Current token age: {age_h:.1f}h · expires in {expires_in:.1f}h"
                if tok and age_h is not None and expires_in is not None
                else "No active token stored"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Yes, update now", callback_data="reminder_yes"),
                        InlineKeyboardButton("❌ No, remind later", callback_data="reminder_no"),
                    ]
                ]
            )
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⏰ *Scheduled Dhan token check*\n\n"
                    f"{_escape_md(token_state)}\n\n"
                    "Do you want to refresh the token now?"
                ),
                reply_markup=keyboard,
            )
            logger.info("DRISHTI: TYPE 1 token reminder sent at %s IST", time_str)
            app.bot_data["last_type1_reminder_key"] = reminder_key
            await asyncio.sleep(58)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("DRISHTI reminder loop error: %s", exc)


async def _token_age_monitor_loop(app: Application) -> None:
    """Proactive stale-token warnings for standalone DRISHTI (mirrors main.py monitor)."""
    params = app.bot_data.get("params", {}) or {}
    warning_minutes = int((params.get("alerts") or {}).get("token_expiry_warning_minutes", 60))
    chat_id = str(app.bot_data.get("chat_id") or "")
    stale_reported = False

    while True:
        await asyncio.sleep(900)
        try:
            tok, _ = _TOKEN_STORE.load()
            if not tok:
                stale_reported = False
                continue

            age_h = _TOKEN_STORE.token_age_hours() or 0.0
            expires_in = _TOKEN_STORE.effective_expires_in_hours()

            if expires_in is not None and expires_in <= 0:
                if not app.bot_data.get("feed_deactivated_for_expiry"):
                    app.bot_data["feed_deactivated_for_expiry"] = True
                    from bat_telegram.bots.drishti.nifty_feed_integration import (
                        _FEED_BLOCK_KEY,
                    )

                    app.bot_data[_FEED_BLOCK_KEY] = (
                        "Token expired — tap Update Token to restart live feed"
                    )
                    deactivate_ltp_feed(app)
                    if chat_id:
                        try:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    "🔴 <b>Token expired</b> — live NIFTY feed stopped.\n"
                                    "Paste a fresh JWT via <b>Update Token</b>."
                                ),
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception as exc:
                            logger.warning("Token-expiry feed stop alert failed: %s", exc)
                continue
            app.bot_data.pop("feed_deactivated_for_expiry", None)

            if age_h >= 20.0:
                if not stale_reported and chat_id:
                    stale_reported = True
                    await publish_incident(
                        source="drishti",
                        scenario="stale_token",
                        severity="major",
                        category="connectivity",
                        title="Broker token is stale",
                        error_message=(
                            f"Token age {age_h:.1f}h exceeds 20h safe window — refresh before trading."
                        ),
                        next_action="Send a fresh Dhan JWT via Update Token.",
                        source_bot=app.bot,
                        source_chat_id=chat_id,
                    )
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                "⚠️ <b>Token stale</b> — age "
                                f"{age_h:.1f}h (20h safe limit).\n"
                                "Paste a fresh JWT via <b>Update Token</b>."
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as exc:
                        logger.warning("Stale-token local alert failed: %s", exc)
            elif stale_reported:
                stale_reported = False
                await resolve_incident(
                    source="drishti",
                    scenario="stale_token",
                    resolution_message="A fresh broker token is now active.",
                    source_bot=app.bot,
                    source_chat_id=chat_id,
                )

            if (
                expires_in is not None
                and 0 < expires_in * 60.0 <= float(warning_minutes)
                and chat_id
            ):
                warn_key = f"{datetime.now(_IST).date().isoformat()}:expiry"
                if app.bot_data.get("last_expiry_warn_key") != warn_key:
                    app.bot_data["last_expiry_warn_key"] = warn_key
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                "🟠 <b>Token expiring soon</b>\n\n"
                                f"Effective expiry in <b>{expires_in:.1f}h</b>.\n"
                                "Tap <b>Update Token</b> before market needs it."
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as exc:
                        logger.warning("Expiry warning failed: %s", exc)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("DRISHTI token age monitor error: %s", exc)


async def _drishti_post_init(application: Application) -> None:
    """Start DRISHTI background coroutines after PTB Application.initialize()."""
    application.bot_data["started_at_ist"] = datetime.now(_IST).strftime("%d-%b-%Y %H:%M:%S IST")
    params = application.bot_data.get("params") or {}
    tok, _ = _TOKEN_STORE.load()
    if tok and not _TOKEN_STORE.is_expired():
        ensure_default_feed_config(params)

    register_shutdown_callback(application, lambda: deactivate_ltp_feed(application))
    create_managed_task(
        application,
        "drishti_reminder_scheduler",
        _reminder_scheduler_loop(application),
        name="drishti_reminder_scheduler",
    )
    create_managed_task(
        application,
        "drishti_token_age_monitor",
        _token_age_monitor_loop(application),
        name="drishti_token_age_monitor",
    )
    create_managed_task(
        application,
        "drishti_feed_watchdog",
        feed_watchdog_loop(application, _TOKEN_STORE),
        name="drishti_feed_watchdog",
    )
    create_managed_task(
        application,
        "drishti_feed_recovery_watchdog",
        feed_recovery_watchdog_loop(application, _TOKEN_STORE),
        name="drishti_feed_recovery_watchdog",
    )
    create_managed_task(
        application,
        "drishti_uat_replay_watchdog",
        uat_market_replay_watchdog_loop(application),
        name="drishti_uat_replay_watchdog",
    )
    restart_nifty_feed(application, _TOKEN_STORE)
    block = application.bot_data.get("nifty_feed_block_reason")
    chat_id = application.bot_data.get("chat_id")
    if isinstance(block, str) and block and chat_id:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🟠 <b>Live NIFTY feed not started</b>\n\n"
                    f"{html.escape(block)}"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.warning("DRISHTI feed-block notice failed: %s", exc)
    logger.info("DRISHTI: background coroutines started ✓")
