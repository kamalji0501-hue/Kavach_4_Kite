from __future__ import annotations

import asyncio
import csv
import html
import json
import logging
import re
import zoneinfo
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bat_telegram.loader import load_bot_config
from core.batman_mode import is_uat
from core.saransh_paths import (
    deployment_dir,
    legacy_telemetry_csv_path,
    saransh_analytics_dir,
)
from core.saransh_reporting import (
    load_deployment_protect_strikes,
    load_live_ato_status,
    load_today_completed_cycles,
    render_ato_cycle_messages,
    write_session_xlsx,
)
from core.ato_cycle_feed import read_cycle_state
from core.saransh_session_sync import read_session_manifest
from core.token_store import TokenStore
from core.utils import is_trading_day
from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode

logger = logging.getLogger("batman.saransh")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY_DIR = deployment_dir(_WORKSPACE_ROOT)
_TELEMETRY_PATH = legacy_telemetry_csv_path(_WORKSPACE_ROOT)
_SUMMARY_DIR = saransh_analytics_dir(_WORKSPACE_ROOT)
_TOKEN_STORE = TokenStore(path=_WORKSPACE_ROOT / "data" / "access_token.json")
_CB_MENU = "sar_menu"
_HELP = (
    "📊 <b>SARANSH — Reporting</b>\n\n"
    "🔄 <b>ATO Cycle</b> — round trips + point impact (live)\n"
    "📋 <b>Daily Summary</b> — session P&amp;L recap\n"
    "🩺 <b>Status</b> — session readiness\n\n"
    "<i>Slash commands</i> <code>/summary</code> <i>and</i> <code>/status</code> <i>also work.</i>"
)


def _he(text: Any) -> str:
    """HTML-escape dynamic values for Telegram HTML parse mode."""
    return html.escape(str(text), quote=False)


def _strip_html(text: str) -> str:
    """Plain-text version of an HTML message for the analytics log file."""
    text = re.sub(r"<[^>]+>", "", text)
    return (
        text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    )


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    """Three inline buttons attached to the alive card (KAVACH2-style)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 ATO Cycle", callback_data=f"{_CB_MENU}:ato_cycle"),
                InlineKeyboardButton(
                    "📋 Daily Summary", callback_data=f"{_CB_MENU}:daily_summary"
                ),
            ],
            [InlineKeyboardButton("🩺 Status", callback_data=f"{_CB_MENU}:status")],
        ]
    )


async def _clear_bottom_reply_keyboard(bot, chat_id: int | str) -> None:
    """Force-remove Telegram's bottom/side reply keyboard (legacy SARANSH UI).

    Sends a transient Remove markup, then deletes the message so the chat is not
    littered with "Menu updated" notices on every bot restart.
    """
    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=".",
            reply_markup=ReplyKeyboardRemove(selective=False),
            disable_notification=True,
        )
        # Brief pause so clients apply ReplyKeyboardRemove before delete.
        await asyncio.sleep(0.4)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
        except Exception as del_exc:
            logger.debug("SARANSH keyboard-clear delete soft-failed: %s", del_exc)
    except Exception as exc:
        logger.warning("SARANSH reply-keyboard clear failed: %s", exc)


def apply_saransh_paths(workspace_root: Path) -> None:
    """Point SARANSH data paths at data/{mode}/ (called from run_saransh.py)."""
    global _WORKSPACE_ROOT, _DEPLOY_DIR, _TELEMETRY_PATH, _SUMMARY_DIR, _TOKEN_STORE
    _WORKSPACE_ROOT = workspace_root
    _DEPLOY_DIR = deployment_dir(workspace_root)
    _TELEMETRY_PATH = legacy_telemetry_csv_path(workspace_root)
    _SUMMARY_DIR = saransh_analytics_dir(workspace_root)
    _TOKEN_STORE = TokenStore(path=workspace_root / "data" / "access_token.json")


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


def _today_ist() -> datetime:
    return datetime.now(_IST)


def _find_active_deployment() -> dict[str, Any] | None:
    files = sorted(_DEPLOY_DIR.glob("batman_*.json"))
    if not files:
        return None
    try:
        with open(files[-1], encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
    except Exception as exc:
        logger.warning("SARANSH deployment read failed: %s", exc)
    return None


def _parse_ist_timestamp(raw_ts: str) -> datetime | None:
    """Parse telemetry timestamps like ``2026-07-17 04:28:58 IST``."""
    text = (raw_ts or "").strip()
    if not text:
        return None
    if text.endswith(" IST"):
        text = text[: -len(" IST")].strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_IST)
    return parsed


def _parse_telemetry_today() -> list[dict[str, str]]:
    if not _TELEMETRY_PATH.exists():
        return []
    rows: list[dict[str, str]] = []
    today = _today_ist().date()
    try:
        with open(_TELEMETRY_PATH, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw_ts = (row.get("timestamp_ist") or "").strip()
                if not raw_ts:
                    continue
                parsed = _parse_ist_timestamp(raw_ts)
                if parsed is None:
                    continue
                if parsed.astimezone(_IST).date() == today:
                    rows.append({k: str(v) for k, v in row.items() if k})
    except Exception as exc:
        logger.warning("SARANSH telemetry read failed: %s", exc)
    return rows


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _token_addendum() -> str:
    token, _saved_at = _TOKEN_STORE.load()
    reminder_times = ["09:00", "15:30", "23:00"]
    if not token:
        return (
            "Token: missing | Next action: update now | Reminder windows: 09:00, 15:30, 23:00 IST"
        )

    age_h = _TOKEN_STORE.token_age_hours() or 0.0
    remaining_h = max(0.0, 24.0 - age_h)
    if remaining_h <= 0:
        state = "expired"
        action = "update now"
    elif remaining_h <= 4:
        state = f"stale ({remaining_h:.1f}h left)"
        action = "update before next session"
    else:
        state = f"healthy ({remaining_h:.1f}h left)"
        action = "skip until next reminder window"
    return f"Token: {state} | Next action: {action} | Reminder windows: {', '.join(reminder_times)} IST"


def _compute_summary_payload(broker, config, state) -> dict[str, Any]:
    dep = _find_active_deployment() or {}
    telemetry = _parse_telemetry_today()
    telemetry_missing = not _TELEMETRY_PATH.exists()

    try:
        orderbook = broker.get_orderbook() if broker else None
        total_orders = 0 if orderbook is None else int(len(orderbook.index))
    except Exception as exc:
        logger.warning("SARANSH orderbook fetch failed: %s", exc)
        total_orders = 0

    try:
        total_pnl = float(broker.get_live_pnl()) if broker else 0.0
    except Exception as exc:
        logger.warning("SARANSH live PnL fetch failed: %s", exc)
        total_pnl = 0.0

    try:
        balance = float(broker.get_balance()) if broker else 0.0
    except Exception:
        balance = 0.0

    lot_size = int(config.get("strategy.lot_size", 1)) if config else 1
    buy_lots_default = int(config.get("strategy.buy_lots", 1)) if config else 1
    positions = cast(dict[str, dict[str, Any]], dep.get("positions", {}))
    profile = cast(dict[str, Any], dep.get("profile") or {})
    deployed_lots = buy_lots_default
    pe_buy_qty = _safe_int((positions.get("pe_buy") or {}).get("qty"))
    ce_buy_qty = _safe_int((positions.get("ce_buy") or {}).get("qty"))
    if pe_buy_qty and lot_size > 0:
        deployed_lots = max(1, pe_buy_qty // lot_size)
    elif ce_buy_qty and lot_size > 0:
        deployed_lots = max(1, ce_buy_qty // lot_size)

    one_lot_equivalent = total_pnl / deployed_lots if deployed_lots > 0 else total_pnl
    pnl_pct = (total_pnl / balance * 100.0) if balance > 0 else 0.0

    action_counter = Counter((row.get("side", "?"), row.get("action", "?")) for row in telemetry)
    reason_counter = Counter(row.get("trigger_reason", "unknown") for row in telemetry)
    density_counter: Counter[str] = Counter()
    strike_context_counter: Counter[str] = Counter()
    impact_points = 0.0
    for row in telemetry:
        raw_ts = row.get("timestamp_ist") or ""
        parsed = _parse_ist_timestamp(raw_ts)
        if parsed is not None:
            bucket = parsed.astimezone(_IST).strftime("%H:00")
            density_counter[bucket] += 1
        sell_strike = _safe_float(row.get("sell_strike"))
        ltp = _safe_float(row.get("nifty_ltp_at_execution"))
        trigger_level = row.get("trigger_level_used", "?")
        protect_strike = row.get("protect_strike", "?")
        strike_context_counter[
            f"{row.get('side', '?')}: sell {row.get('sell_strike', '?')} -> trigger {trigger_level} -> protect {protect_strike}"
        ] += 1
        if row.get("action") == "BUY entry" and sell_strike is not None and ltp is not None:
            impact_points += abs(ltp - sell_strike)

    # Authoritative ATO recap comes from the JSONL cycle feed (same source as the
    # ATO Cycle screen) + live state — with ATO/protect strikes, not sell strikes.
    cycles = load_today_completed_cycles(root=_WORKSPACE_ROOT)
    cycle_state = read_cycle_state(root=_WORKSPACE_ROOT)
    ato_fallback = load_deployment_protect_strikes(root=_WORKSPACE_ROOT)
    # Net impact = sum of ATO premium P&L (sell − buy of the protect option),
    # derived from guarded cycles (ignore raw state to resist test writes).
    net_point_impact = round(sum(c.premium_diff for c in cycles), 2)

    side_breakdown: dict[str, dict[str, Any]] = {}
    for c in cycles:
        side = c.side.upper()
        entry = side_breakdown.setdefault(side, {"trips": 0, "impact": 0.0, "ato": set()})
        entry["trips"] += 1
        entry["impact"] += float(c.premium_diff)
        ato_val = c.protect_strike or ato_fallback.get(side)
        if ato_val:
            entry["ato"].add(int(ato_val))
    # Serialize sets to sorted lists for thread/return safety.
    for entry in side_breakdown.values():
        entry["ato"] = sorted(entry["ato"])

    # Live ATO status from the shared batman_state.json — same source as the
    # KAVACH2 ATO Status card — so SARANSH agrees with KAVACH2 even when the
    # protect leg is pre-bought (custom economy profile → no cycle-feed row).
    live_ato = load_live_ato_status(root=_WORKSPACE_ROOT)
    holdings: list[dict[str, Any]] = []
    for side in ("CE", "PE"):
        info = live_ato.get(side) or {}
        if not (info.get("triggered") or info.get("active")):
            continue
        ato_val = info.get("protect_strike") or ato_fallback.get(side)
        leg = cycle_state.get(side.lower()) or {}
        since = leg.get("holding_since_ist") or ""
        if isinstance(since, str) and " " in since:
            since = since.split(" ")[1][:5]
        holdings.append(
            {
                "side": side,
                "ato": ato_val,
                "since": since,
                "state": "holding ATO" if info.get("active") else "ATO triggered",
            }
        )

    return {
        "generated_at": _today_ist().strftime("%H:%M IST, %d %b %Y"),
        "deployment_file": dep.get("file_name") or dep.get("file") or "none",
        "economy_profile": bool(profile.get("custom_ato_economy_profile")),
        "custom_protect_strike": bool(profile.get("custom_protect_strike")),
        "ce_protect_mode": dep.get("ce_protect_strike_mode")
        or (dep.get("ato") or {}).get("ce_protect_strike_mode"),
        "pe_protect_mode": dep.get("pe_protect_strike_mode")
        or (dep.get("ato") or {}).get("pe_protect_strike_mode"),
        "total_orders": total_orders,
        "total_ato_orders": len(telemetry),
        "impact_points": round(impact_points, 1),
        "total_pnl": total_pnl,
        "deployed_lots": deployed_lots,
        "one_lot_equivalent": one_lot_equivalent,
        "pnl_pct": pnl_pct,
        "action_counter": action_counter,
        "reason_counter": reason_counter,
        "density_counter": density_counter,
        "strike_context_counter": strike_context_counter,
        "token_addendum": _token_addendum(),
        "telemetry_missing": telemetry_missing,
        "telemetry_empty": not telemetry,
        "algo_paused": bool(state.get("algo.paused", False)) if state else False,
        "round_trips": len(cycles),
        "net_point_impact": round(net_point_impact, 1),
        "side_breakdown": side_breakdown,
        "holdings": holdings,
    }


def _render_summary(payload: dict[str, Any]) -> str:
    """Readable HTML Daily Summary — compact: header, P&L, ATO trips, orders."""
    algo_icon = "⏸️ Paused" if payload.get("algo_paused") else "🟢 Running"

    total_pnl = float(payload.get("total_pnl", 0.0))
    pnl_icon = "🟢" if total_pnl >= 0 else "🔴"
    net_impact = float(payload.get("net_point_impact", 0.0))
    impact_icon = "🟢" if net_impact >= 0 else "🔴"

    lines: list[str] = [
        "📋 <b>SARANSH — Daily Summary</b>",
        f"<code>{_he(payload['generated_at'])}</code>",
        "",
        f"📦 <b>Deployment:</b> <code>{_he(payload['deployment_file'])}</code>",
        "",
        f"⚙️ <b>Algo:</b> {algo_icon}",
        "",
        f"{pnl_icon} <b>P&amp;L</b>",
        f"   Running: <code>Rs {total_pnl:+,.2f}</code>",
        "",
        f"🔄 <b>ATO Round Trips Today:</b> {payload.get('round_trips', 0)}",
        "",
        f"{impact_icon} <b>Net Point Impact:</b> <code>{net_impact:+.2f}</code>",
    ]

    side_breakdown = cast(dict[str, dict[str, Any]], payload.get("side_breakdown") or {})
    if any(side_breakdown.get(s) for s in ("CE", "PE")):
        lines.append("")
    for side in ("CE", "PE"):
        entry = side_breakdown.get(side)
        if not entry:
            continue
        ato_list = entry.get("ato") or []
        ato_txt = ", ".join(str(s) for s in ato_list) if ato_list else "—"
        lines.append(
            f"<b>{side}:</b> {entry['trips']}\u00a0Trip(s) · ATO\u00a0<b>{_he(ato_txt)}</b>"
            f" · Impact\u00a0<code>{float(entry.get('impact', 0.0)):+.2f}</code>"
        )

    holdings = cast(list[dict[str, Any]], payload.get("holdings") or [])
    if holdings:
        lines.append("")
        lines.append("🔴 <b>Live ATO status</b>")
        for h in holdings:
            ato = h.get("ato") or "—"
            state_word = h.get("state") or "ATO active"
            since = h.get("since") or ""
            since_txt = f" since {_he(since)}" if since else ""
            lines.append(
                f"   {h['side']}: {_he(state_word)} — protect <b>{_he(ato)}</b>{since_txt}"
            )

    lines.append("")
    lines.append(f"📥 <b>Orders Today:</b> {payload.get('total_orders', 0)}")

    return "\n".join(lines)


def _broker_order_counts(broker) -> tuple[int | None, int | None]:
    if broker is None:
        return None, None
    try:
        orderbook = broker.get_orderbook()
        if orderbook is None:
            return None, None
        today_n = 0
        for idx in range(len(orderbook.index)):
            row = orderbook.iloc[idx]
            raw_ts = str(row.get("order_time") or row.get("timestamp") or "")
            try:
                if _today_ist().strftime("%Y-%m-%d") in raw_ts:
                    today_n += 1
            except Exception:
                pass
        return today_n, int(len(orderbook.index))
    except Exception as exc:
        logger.warning("SARANSH order counts failed: %s", exc)
        return None, None


async def _send_summary(app: Application, *, manual: bool) -> None:
    payload = await asyncio.to_thread(
        _compute_summary_payload,
        app.bot_data.get("broker"),
        app.bot_data.get("config"),
        app.bot_data.get("state"),
    )
    header_icon = "✍️ <i>Manual</i>" if manual else "🕒 <i>Auto EOD</i>"
    summary_html = _render_summary(payload)
    summary_plain = _strip_html(summary_html)
    ts = _today_ist()

    telegram_ok = False
    file_ok = False
    send_err: str | None = None
    file_err: str | None = None

    try:
        await app.bot.send_message(
            chat_id=app.bot_data["chat_id"],
            text=summary_html,
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        telegram_ok = True
    except Exception as exc:
        send_err = str(exc)
        logger.error("SARANSH summary Telegram send failed: %s", exc)

    try:
        _SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _SUMMARY_DIR / f"summary_{ts.strftime('%Y%m%d')}.log"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"[{ts.strftime('%H:%M:%S IST')}] source={header_icon}\n")
            fh.write(summary_plain)
            fh.write("\n" + "-" * 80 + "\n")
        file_ok = True
    except Exception as exc:
        file_err = str(exc)
        logger.error("SARANSH summary file write failed: %s", exc)

    if not telegram_ok or not file_ok:
        logger.error(
            "SARANSH summary delivery partial failure telegram=%s file=%s send=%s file_err=%s",
            telegram_ok,
            file_ok,
            send_err,
            file_err,
        )

    try:
        await asyncio.to_thread(
            write_session_xlsx,
            root=_WORKSPACE_ROOT,
            summary_payload=payload,
        )
    except Exception as exc:
        logger.warning("SARANSH XLSX append on summary soft-failed: %s", exc)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bat_telegram.alive_branding import reply_alive_card

    message = _require_message(update)
    await _clear_bottom_reply_keyboard(context.bot, message.chat_id)
    now = _today_ist().strftime("%d-%b-%Y %H:%M:%S IST")
    await reply_alive_card(
        message,
        "🟢 <b>SARANSH ACTIVE</b>\n"
        f"<code>{now}</code>",
        reply_markup=_main_menu_keyboard(),
    )


async def _reply_ato_cycle(message: Message, app: Application) -> None:
    broker = app.bot_data.get("broker")
    orders_today, orders_alltime = await asyncio.to_thread(_broker_order_counts, broker)
    chunks = await asyncio.to_thread(
        render_ato_cycle_messages,
        root=_WORKSPACE_ROOT,
        orders_today=orders_today,
        orders_alltime=orders_alltime,
    )
    for idx, chunk in enumerate(chunks):
        await message.reply_text(
            chunk,
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard() if idx == len(chunks) - 1 else None,
        )
    cycles = await asyncio.to_thread(load_today_completed_cycles, root=_WORKSPACE_ROOT)
    await asyncio.to_thread(write_session_xlsx, root=_WORKSPACE_ROOT, cycles=cycles)


_SUMMARY_ACK = (
    "✅ <b>Daily summary sent.</b>\n"
    "<i>Tap</i> <b>Daily Summary</b> <i>or</i> <code>/summary</code> <i>any time for a fresh recap.</i>"
)


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _require_message(update)
    await _send_summary(context.application, manual=True)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await message.reply_text(
        _status_text(context),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


def _status_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    telemetry_state = "🟢 Present" if _TELEMETRY_PATH.exists() else "🔴 Missing"
    manifest = read_session_manifest(root=_WORKSPACE_ROOT) or {}
    session_status = manifest.get("status") or ("armed" if _find_active_deployment() else "idle")
    session_icon = "🟢" if session_status == "armed" else "⚪"
    schedule = context.bot_data.get("params", {}).get("schedule", {}).get("eod_time_ist", "15:35")
    mode = "UAT" if is_uat(_WORKSPACE_ROOT) else "dev/prod"
    return (
        "🩺 <b>SARANSH — STATUS</b>\n\n"
        f"{session_icon} <b>Session:</b> {_he(str(session_status).capitalize())}\n"
        f"🆔 <b>Session ID:</b> <code>{_he(manifest.get('session_id', '—'))}</code>\n"
        f"🕒 <b>Deployed:</b> {_he(manifest.get('deployed_at_ist', '—'))}\n"
        f"📄 <b>Telemetry CSV:</b> {telemetry_state}\n"
        f"🌐 <b>Mode:</b> {mode}\n"
        f"⏰ <b>Auto Summary:</b> {_he(schedule)} IST <i>(Trading Days Only)</i>"
    )


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _require_query(update)
    await query.answer()
    action = (query.data or "").split(":")[-1]
    message = query.message
    if not isinstance(message, Message):
        return

    if action == "ato_cycle":
        await _reply_ato_cycle(message, context.application)
        return
    if action == "daily_summary":
        await _send_summary(context.application, manual=True)
        return
    if action == "status":
        await message.reply_text(
            _status_text(context),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(),
        )
        return
    await message.reply_text(_HELP, parse_mode=ParseMode.HTML, reply_markup=_main_menu_keyboard())


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    text = (message.text or "").strip().lower()
    if text in ("hello", "hi", "/menu", "menu"):
        await cmd_start(update, context)
        return
    # Legacy bottom-keyboard labels still work once, then show inline menu.
    if text == "ato cycle":
        await _reply_ato_cycle(message, context.application)
        return
    if text == "daily summary":
        await cmd_summary(update, context)
        return
    if text == "status":
        await cmd_status(update, context)
        return
    await message.reply_text(_HELP, parse_mode=ParseMode.HTML, reply_markup=_main_menu_keyboard())


async def _eod_summary_loop(app: Application) -> None:
    schedule = app.bot_data.get("params", {}).get("schedule", {}).get("eod_time_ist", "15:35")
    last_sent_date = None
    while True:
        await asyncio.sleep(30)
        try:
            now = _today_ist()
            if not is_trading_day(now.date()):
                continue
            if now.strftime("%H:%M") != schedule:
                continue
            if last_sent_date == now.date():
                continue
            last_sent_date = now.date()
            await _send_summary(app, manual=False)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("SARANSH EOD loop error: %s", exc)


async def _send_restart_ack(application: Application) -> None:
    try:
        from core.saransh_session_sync import clear_restart_reason, read_session_manifest

        manifest = read_session_manifest()
        if not manifest:
            return
        reason = manifest.get("restart_reason")
        if not reason:
            return
        chat_id = application.bot_data.get("chat_id")
        if reason == "batman_complete":
            text = (
                "Batman Complete acknowledged. SARANSH restarted. "
                "No active session — run /register on KAVACH2 when ready."
            )
        elif reason == "register_confirm":
            deployed = manifest.get("deployed_at_ist") or "unknown"
            text = (
                f"New Batman session armed. SARANSH restarted. "
                f"Deployed: {deployed}. Use ATO Cycle for live recap."
            )
        else:
            return
        await application.bot.send_message(chat_id=chat_id, text=text)
        await asyncio.to_thread(clear_restart_reason)
    except Exception as exc:
        logger.warning("SARANSH restart ack soft-failed: %s", exc)


async def _saransh_post_init(application: Application) -> None:
    asyncio.create_task(_eod_summary_loop(application))
    asyncio.create_task(_send_restart_ack(application))
    # Do NOT auto-clear reply keyboard on every restart — that spammed
    # "Menu updated…" into the chat. Clear only on /start when the user opens SARANSH.
    logger.info("SARANSH: background coroutines started")


def build_application(broker=None, state=None, event_bus=None, config=None) -> Application:
    del event_bus
    cfg = load_bot_config("saransh")
    app = (
        Application.builder()
        .token(cfg.bot_token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(60.0)
        .media_write_timeout(60.0)
        .post_init(_saransh_post_init)
        .build()
    )
    app.bot_data["broker"] = broker
    app.bot_data["state"] = state
    app.bot_data["config"] = config
    app.bot_data["chat_id"] = cfg.chat_id
    app.bot_data["params"] = cfg.params
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("summary_eod", cmd_summary))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(cb_menu, pattern=f"^{_CB_MENU}:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("SARANSH bot application built")
    return app
