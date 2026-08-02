"""
Batman v3 — Local Telegram Simulator
=====================================
Runs active bots (DRISHTI / KAVACH / SANCHALAK / SARANSH / JAGRAN) locally.
LAKSHMI is deferred to a future phase and is disabled in this simulator.
No Telegram API credentials needed.

Start:  python simulator/app.py
Open:   http://localhost:5001
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from unittest.mock import MagicMock

# ── Telegram stub (same as conftest.py) ──────────────────────────────────────
for _m in ("telegram", "telegram.ext", "telegram.error", "telegram.constants"):
    sys.modules.setdefault(_m, MagicMock())

# ── Project root on path ─────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO)
from core.bot_logging import attach_main_incident_handler  # noqa: E402

attach_main_incident_handler(ROOT)

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

from core.batman_cleanup import (  # noqa: E402
    format_cleanup_verification_message,
    verify_batman_cleanup,
)
from core.position_scope import (  # noqa: E402
    qty_to_lots,
    resolve_nifty_lot_size,
    scale_side_flexible,
    side_lots_selection,
)
from core.token_store import TokenStore  # noqa: E402

_SETTINGS_JSON = ROOT / "config" / "settings.json"
try:
    _NIFTY_LOT_SIZE = resolve_nifty_lot_size(
        config_lot_size=int(json.loads(_SETTINGS_JSON.read_text())["strategy"]["lot_size"])
    )
except Exception:
    _NIFTY_LOT_SIZE = 65

_SIM_DEPLOY_DIR = ROOT / "data" / "deployments"

# ── Position data (loaded from mock JSON) ────────────────────────────────────
_MOCK_JSON = ROOT / "testing" / "mocks" / "positions_apr7.json"
_RAW_POSITIONS: list[dict] = json.loads(_MOCK_JSON.read_text())["positions"]

app = Flask(__name__, static_folder=str(Path(__file__).parent), static_url_path="")

# ═══════════════════════════════════════════════════════════════════════════════
# SHARED STATE
# ═══════════════════════════════════════════════════════════════════════════════
_lock = threading.Lock()
_messages: list[dict] = []
_next_id = 1

_token_store = TokenStore(path=ROOT / "testing" / "mocks" / "sim_access_token.json")
_nifty_spot: float = 22713.0
_deployment: dict | None = None
_wizard: dict | None = None
_algo_running: bool = False
_algo_paused: bool = False
_ato: dict = {"ce": False, "pe": False, "ce_cycles": 0, "pe_cycles": 0, "max_cycles": 3}
_batman_complete_pending: bool = False
_exit_pending: bool = False
_awaiting_token_drishti: bool = False  # True after /update_token until user sends a token
_runtime_mode: str = "mock"
_global_enabled: bool = True
_paused_bots: dict[str, bool] = {
    "drishti": False,
    "kavach": False,
    "saransh": False,
    "jagran": False,
}

_READ_ONLY_COMMANDS: dict[str, set[str]] = {
    "drishti": {"/status", "/health", "/ping"},
    "kavach": {"/ato_status", "/ato_report", "/legs", "/funds", "/status"},
    "saransh": {"/status"},
    "jagran": {"/status", "/recent"},
}

# ── Market Simulator state ────────────────────────────────────────────────────
_sim_time: datetime = datetime.now().replace(second=0, microsecond=0)
_algo_events: list = []
_event_id_counter: int = 0
_ato_warn: dict = {"ce": False, "pe": False}  # near-strike warning state
_sim_token_saved_at = None  # datetime | None — sim-clock timestamp when token was last delivered
_ato_trade_ledger: list[dict] = []
_ato_open_entries: dict[str, dict | None] = {"CE": None, "PE": None}

# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _push(
    bot: str, actor: str, text: str, keyboard: list | None = None, mono: bool = False
) -> None:
    global _next_id
    with _lock:
        _messages.append(
            {
                "id": _next_id,
                "bot": bot,
                "actor": actor,
                "text": text,
                "keyboard": keyboard or [],
                "mono": mono,
                "ts": _now_ts(),
            }
        )
        _next_id += 1


def _bot(bot: str, text: str, keyboard: list | None = None, mono: bool = False) -> None:
    _push(bot, "bot", text, keyboard=keyboard, mono=mono)


def _user(bot: str, text: str) -> None:
    _push(bot, "user", text)


def _command_name(text: str) -> str:
    t = text.strip()
    if not t.startswith("/"):
        return ""
    return t.split()[0].lower()


def _is_read_only(bot: str, cmd: str) -> bool:
    return cmd in _READ_ONLY_COMMANDS.get(bot, set())


def _blocked_by_controls(bot: str, cmd: str) -> bool:
    if not cmd:
        return False
    if _paused_bots.get(bot, False) and not _is_read_only(bot, cmd):
        _bot(
            bot,
            f"⏸ {bot.upper()} is paused. This command is blocked. Read-only commands still work.",
        )
        return True
    if not _global_enabled and not _is_read_only(bot, cmd):
        _bot(bot, "⛔ Global controls are stopped by SANCHALAK. Run /start_all in SANCHALAK first.")
        return True
    return False


def _set_bot_paused(bot: str, paused: bool) -> bool:
    if bot not in _paused_bots:
        return False
    _paused_bots[bot] = paused
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# DRISHTI — Token delivery & health
# ═══════════════════════════════════════════════════════════════════════════════

_REMINDER_TIMES_IST = ["09:00", "15:30", "23:00"]


def _sim_token_age_hours():
    """Token age in simulated hours. None if no token delivered this session."""
    if _sim_token_saved_at is None:
        return None
    return (_sim_time - _sim_token_saved_at).total_seconds() / 3600


def _sim_token_expired() -> bool:
    """True if token is absent or >= 24h old under the simulated clock."""
    if _sim_token_saved_at is None:
        return True
    return (_sim_time - _sim_token_saved_at).total_seconds() / 3600 >= 24


def _fire_drishti_reminder() -> None:
    """Push a TYPE 1 interactive token reminder to DRISHTI chat.

    Suppressed if the token is still valid (age < 24 h under sim clock).
    """
    if not _sim_token_expired():
        age = _sim_token_age_hours()
        _log_algo_event(
            "info",
            f"DRISHTI reminder at {_sim_time.strftime('%H:%M')} — suppressed (token {age:.1f}h old, still valid)",
            "",
        )
        return
    time_str = _sim_time.strftime("%H:%M")
    date_str = _sim_time.strftime("%a %d-%b-%Y")
    _bot(
        "drishti",
        (
            f"\u26a0\ufe0f Dhan access token expired (or never set).\n\n"
            f"\U0001f550 {time_str} IST \u00b7 {date_str}\n\n"
            f"Batman cannot trade until you supply a fresh Dhan JWT token.\n\n"
            f"Do you want to update it now?"
        ),
        keyboard=[
            [
                {"text": "\u2705  Yes, Update Now", "data": "reminder_yes"},
                {"text": "\u274c  No, Remind Later", "data": "reminder_no"},
            ]
        ],
    )
    _log_algo_event("warn", f"DRISHTI TYPE 1 reminder fired at {time_str}", "token expired")


def _check_drishti_reminders(old_time: datetime, new_time: datetime) -> None:
    """Auto-fire a TYPE 1 reminder when sim-time crosses a configured reminder slot.

    Checks 09:00, 15:30, 23:00 IST. Fires at most once per time advance.
    Only on weekdays. Token validity check is done inside _fire_drishti_reminder.
    """
    for ts in _REMINDER_TIMES_IST:
        h, m = int(ts[:2]), int(ts[3:])
        reminder_dt = new_time.replace(hour=h, minute=m, second=0, microsecond=0)
        # Slot crossed if boundary falls strictly inside (old_time, new_time]
        if old_time < reminder_dt <= new_time and reminder_dt.weekday() < 5:
            threading.Thread(target=_fire_drishti_reminder, daemon=True).start()
            return  # fire at most once per advance


def _drishti_main_menu_keyboard() -> list[list[dict]]:
    """Mirror DRISHTI Telegram inline menu (Phase 1 — no Fleet)."""
    return [
        [
            {"text": "Health", "data": "drishti:menu:health"},
            {"text": "Token Status", "data": "drishti:menu:status"},
        ],
        [
            {"text": "Update Token", "data": "drishti:menu:update_token"},
            {"text": "Deactivate Token", "data": "drishti:menu:deactivate_token"},
        ],
        [
            {"text": "Ping", "data": "drishti:menu:ping"},
            {"text": "LTP Feed Setup", "data": "drishti:menu:ltp_setup"},
        ],
        [
            {"text": "Nifty LTP (Polling)", "data": "drishti:menu:nifty_ltp_polling"},
            {"text": "Nifty LTP (WebSocket)", "data": "drishti:menu:nifty_ltp_ws"},
        ],
    ]


def _drishti_alive_message() -> str:
    return f"🟢 DRISHTI alive\n" f"Sim : {_sim_time.strftime('%a %d-%b-%Y %H:%M')} IST"


def _handle_drishti(text: str) -> None:
    global _awaiting_token_drishti, _sim_token_saved_at
    t = text.strip()
    cmd = _command_name(t)

    if _blocked_by_controls("drishti", cmd):
        return

    if t == "/start":
        _bot("drishti", _drishti_alive_message(), keyboard=_drishti_main_menu_keyboard())
        return

    if t == "/ping":
        tok_str = (
            f"⚠️ EXPIRED ({_sim_token_age_hours():.1f}h old)"
            if _sim_token_saved_at and _sim_token_expired()
            else (
                f"✅ valid ({_sim_token_age_hours():.1f}h old)"
                if _sim_token_saved_at
                else "🔴 none"
            )
        )
        _bot(
            "drishti",
            f"{_drishti_alive_message()}\nToken: {tok_str}",
            keyboard=_drishti_main_menu_keyboard(),
        )
        return

    if t == "/health":
        has_token = _sim_token_saved_at is not None or _token_store.load()[0] is not None
        age_h = _sim_token_age_hours()
        expired = _sim_token_expired()
        if not has_token:
            tok_line = "🔴 No token"
        elif expired:
            tok_line = f"⚠️ EXPIRED ({age_h:.1f}h old)"
        else:
            tok_line = f"✅ Active ({age_h:.1f}h old)"
        _bot(
            "drishti",
            (
                f"🔍 System Health\n\n"
                f"Sim time   : {_sim_time.strftime('%H:%M IST · %a %d-%b')}\n"
                f"NIFTY LTP  : ₹{_nifty_spot:,.2f} ✓\n"
                f"Broker     : {'✅ Connected' if has_token and not expired else '🔴 Disconnected (token expired)' if expired else '🔴 No token'}\n"
                f"Token      : {tok_line}\n"
                f"Algo       : {'▶ Running' if _algo_running else '⏸ Idle'}\n"
                f"Deployment : {'✅ Armed' if _deployment else '⏳ Not deployed'}"
            ),
        )
        return

    if t == "/status":
        has_token = _sim_token_saved_at is not None or _token_store.load()[0] is not None
        if not has_token:
            _bot("drishti", "🔴 No token stored.\n\nUse /update_token to connect the broker.")
            return
        age_h = _sim_token_age_hours() or 0
        expires_in = max(0.0, 24.0 - age_h)
        expired = age_h >= 24
        tok_status = "⚠️ EXPIRED — update required!" if expired else "✅ Active"
        saved_str = (
            _sim_token_saved_at.strftime("%H:%M IST") if _sim_token_saved_at else "pre-loaded"
        )
        _bot(
            "drishti",
            (
                f"🔍 Token Status\n\n"
                f"Sim time  : {_sim_time.strftime('%H:%M IST')}\n"
                f"Status    : {tok_status}\n"
                f"Age       : {age_h:.1f}h (sim clock)\n"
                f"Expires   : {'NOW — EXPIRED!' if expired else f'in {expires_in:.1f}h'}\n"
                f"Delivered : {saved_str}"
            ),
        )
        return

    if t == "/update_token":
        _awaiting_token_drishti = True
        age_h = _sim_token_age_hours()
        if age_h is not None:
            current_info = f"Current token: {age_h:.1f}h old (sim clock){'  ⚠️ EXPIRED' if age_h >= 24 else ''}"
        else:
            current_info = "No token delivered in this session"
        _bot(
            "drishti",
            (
                f"🔄 Update Dhan Access Token\n\n"
                f"{current_info}\n\n"
                f"Please paste your fresh Dhan JWT access token now.\n"
                f"Get it from: web.dhan.co → Profile → Access DhanHQ APIs"
            ),
        )
        return

    if t == "/deactivate_token":
        has_token = _sim_token_saved_at is not None or _token_store.load()[0] is not None
        if not has_token:
            _bot("drishti", "ℹ️ No active token to deactivate.\n\nUse /update_token to connect.")
            return
        age_h = _sim_token_age_hours() or 0
        _token_store.clear()
        _sim_token_saved_at = None
        _awaiting_token_drishti = False
        _bot(
            "drishti",
            (
                f"🔴 Token deactivated.\n\n"
                f"Token was {age_h:.1f}h old (sim clock)\n\n"
                f"Broker is now disconnected.\n"
                f"Use /update_token to reconnect when you have a fresh Dhan JWT."
            ),
        )
        return

    if t == "/nifty_ltp":
        _bot(
            "drishti",
            (
                f"📈 NIFTY LTP (Polling)\n\n"
                f"Price : ₹{_nifty_spot:,.2f}\n"
                f"Source: Polling — sim REST cache\n"
                f"As of : {_sim_time.strftime('%H:%M IST')}"
            ),
            keyboard=_drishti_main_menu_keyboard(),
        )
        return

    # JWT detection OR awaiting_token flow
    is_jwt = len(t) > 30 and not t.startswith("/") and " " not in t and "." in t
    if is_jwt or (_awaiting_token_drishti and not t.startswith("/")):
        _token_delivery(t)
        return

    _DRISHTI_HELP = (
        "/update_token      — Paste a fresh Dhan JWT token\n"
        "/deactivate_token  — Revoke current token & disconnect broker\n"
        "/status            — Token age & expiry countdown\n"
        "/health            — Full system health check\n"
        "/ping              — Liveness check\n\n"
        "Or paste your Dhan JWT token directly at any time."
    )
    if t.lower() in ("hello", "hi"):
        _bot(
            "drishti",
            "👁 Hello! I'm DRISHTI, your infrastructure & token bot.\n\n" + _DRISHTI_HELP,
            keyboard=_drishti_main_menu_keyboard(),
        )
        return
    _bot("drishti", f"❌ Invalid command: {t}\n\n" + _DRISHTI_HELP)


def _token_delivery(token: str) -> None:
    global _awaiting_token_drishti, _sim_token_saved_at
    _awaiting_token_drishti = False
    _bot("drishti", "⏳ Token received. Connecting to Dhan broker…")
    time.sleep(0.5)
    _token_store.save(token)
    _sim_token_saved_at = _sim_time  # record sim-clock time of delivery
    sim_expiry_str = (_sim_token_saved_at + timedelta(hours=24)).strftime("%H:%M IST")
    _bot(
        "drishti",
        (
            f"✅ Broker connected!\n\n"
            f"NIFTY LTP (Polling): ₹{_nifty_spot:,.2f} ✓\n"
            f"GIFT Nifty : ₹{_nifty_spot - 5.0:,.2f} ✓\n\n"
            f"Token saved → testing/mocks/sim_access_token.json\n"
            f"Sim time   : {_sim_time.strftime('%H:%M IST')}\n"
            f"Expires    : {sim_expiry_str} (24h — advance clock to test)\n\n"
            f"🦇 Batman is ready.\n"
            f"Open KAVACH and run /register to register your positions."
        ),
        keyboard=_drishti_main_menu_keyboard(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# KAVACH — Deploy wizard + trading commands
# ═══════════════════════════════════════════════════════════════════════════════


def _handle_kavach(text: str) -> None:
    global _algo_running, _algo_paused, _deployment, _wizard
    global _batman_complete_pending, _exit_pending
    t = text.strip()
    cmd = _command_name(t)

    if _blocked_by_controls("kavach", cmd):
        return

    # ── /register ───────────────────────────────────────────────────────────────
    if t == "/register":
        token, _ = _token_store.load()
        if token is None or _sim_token_expired():
            age_str = f"{_sim_token_age_hours():.0f}h old" if token is not None else "never set"
            _bot(
                "kavach",
                (
                    "🔒 Token Required\n\n"
                    f"DRISHTI reports no valid Dhan access token ({age_str}).\n"
                    "Batman cannot fetch positions without a live broker connection.\n\n"
                    "👉 Open DRISHTI → send your fresh Dhan JWT, then retry /register."
                ),
            )
            return
        _wizard_start()
        return

    # ── /ato_status ──────────────────────────────────────────────────────────
    if t == "/ato_status":
        _show_ato()
        return

    # ── /ato_report ─────────────────────────────────────────────────────────
    if t == "/ato_report":
        snap = _sim_ato_ledger_snapshot()
        rows = snap.get("rows", [])
        if not rows:
            _bot(
                "kavach",
                "📊 ATO Report\n\nNo closed ATO cycles yet today.\nTrigger and close at least one ATO cycle to view buy/sell times and points lost.",
            )
            return
        last = rows[-1]
        _bot(
            "kavach",
            (
                f"📊 ATO Report ({snap['date_ist']})\n\n"
                f"Closed cycles today: {snap['closed_cycles_today']}\n"
                f"Total points lost: {snap['total_points_lost_today']:.2f}\n"
                f"Total points lost × lots: {snap['total_points_lost_x_lots_today']:.2f}\n\n"
                f"Last cycle ({last['side']} #{last['cycle_index']}):\n"
                f"Buy : {last['buy_timestamp_ist']} @ {last['buy_nifty_ltp']}\n"
                f"Sell: {last['sell_timestamp_ist']} @ {last['sell_nifty_ltp']}\n"
                f"Points lost: {last['points_lost']:.2f} (x lots: {last['points_lost_x_lots']:.2f})"
            ),
        )
        return

    # ── /pause ────────────────────────────────────────────────────────────────
    if t == "/pause":
        if not _deployment:
            _bot("kavach", "⚠️ No deployment registered. Run /register first.")
            return
        _algo_paused = True
        _bot("kavach", "⏸ Algo paused. ATO monitoring suspended.\nSend /resume to restart.")
        return

    # ── /resume ───────────────────────────────────────────────────────────────
    if t == "/resume":
        if not _deployment:
            _bot("kavach", "⚠️ No deployment. Run /register first.")
            return
        _algo_paused = False
        _bot("kavach", "▶ Algo resumed. ATO monitoring active.")
        return

    # ── /start_algo_now ────────────────────────────────────────────────────────────
    if t == "/start_algo_now":
        if not _deployment:
            _bot("kavach", "⚠️ No deployment. Run /register first.")
            return
        _algo_running = True
        ato = _deployment["ato"]
        ce_trigger = int(ato.get("ce_sell_strike", 0)) + int(ato.get("ce_entry_buffer_points", 0))
        pe_trigger = int(ato.get("pe_sell_strike", 0)) - int(ato.get("pe_entry_buffer_points", 0))
        _bot(
            "kavach",
            (
                f"▶ Algo started immediately!\n\n"
                f"ATO monitoring is now active.\n"
                f"CE trigger: {ce_trigger:,} (ATO {ato['ce_protect_strike']:,})\n"
                f"PE trigger: {pe_trigger:,} (ATO {ato['pe_protect_strike']:,})"
            ),
        )
        return

    # ── /batman_complete ──────────────────────────────────────────────────────
    if t == "/batman_complete":
        if not _deployment:
            _bot("kavach", "⚠️ No active deployment to complete.")
            return
        _batman_complete_pending = True
        _bot(
            "kavach",
            "⚠️ Batman Complete?\n\n"
            "This will:\n"
            "• Stop ATO monitoring\n"
            "• Archive the deployment file\n"
            "• Reset the algo for next week",
            keyboard=[
                [
                    {"text": "✅  Yes — Complete", "data": "complete:confirm"},
                    {"text": "❌  Cancel", "data": "complete:cancel"},
                ]
            ],
        )
        return

    # ── /exit ─────────────────────────────────────────────────────────────────
    if t == "/exit":
        if not _deployment:
            _bot("kavach", "⚠️ No active deployment to exit.")
            return
        if _runtime_mode != "live":
            _bot(
                "kavach",
                "⛔ Runtime mode is MOCK. Emergency market orders are blocked. Use SANCHALAK /set_mode live first.",
            )
            return
        _exit_pending = True
        _bot(
            "kavach",
            "🚨 Emergency Exit?\n\n"
            "This will CLOSE ALL POSITIONS at market price immediately.\n"
            "This CANNOT be undone.",
            keyboard=[
                [
                    {"text": "✅  Yes — Close all now", "data": "exit:confirm"},
                    {"text": "❌  Cancel", "data": "exit:cancel"},
                ]
            ],
        )
        return

    # ── /legs ─────────────────────────────────────────────────────────────────
    if t == "/legs":
        if not _deployment:
            _bot("kavach", "⚠️ No active deployment. Run /register first.")
            return
        p = _deployment["positions"]
        _bot(
            "kavach",
            (
                f"🦇 Current Batman Legs\n"
                f"{'─'*44}\n"
                f"PE BUY  : {p['pe_buy']['symbol']:<24} qty={p['pe_buy']['qty']:<6} avg=₹{p['pe_buy']['avg_price']}\n"
                f"PE SELL : {p['pe_sell']['symbol']:<24} qty={p['pe_sell']['qty']:<6} avg=₹{p['pe_sell']['avg_price']}\n"
                f"CE SELL : {p['ce_sell']['symbol']:<24} qty={p['ce_sell']['qty']:<6} avg=₹{p['ce_sell']['avg_price']}\n"
                f"CE BUY  : {p['ce_buy']['symbol']:<24} qty={p['ce_buy']['qty']:<6} avg=₹{p['ce_buy']['avg_price']}"
            ),
            mono=True,
        )
        return

    # ── /funds ────────────────────────────────────────────────────────────────
    if t == "/funds":
        _bot(
            "kavach",
            "💰 Available Margin\n\nUsed    : ₹2,45,800\nFree    : ₹2,54,200\nTotal   : ₹5,00,000",
        )
        return

    # ── /status ───────────────────────────────────────────────────────────────
    if t == "/status":
        tok_ok = _token_store.load()[0] is not None
        algo_str = (
            "▶ Running"
            if (_algo_running and not _algo_paused)
            else ("⏸ Paused" if _algo_paused else "⏳ Idle")
        )
        _bot(
            "kavach",
            (
                f"🛡 KAVACH Status\n\n"
                f"Broker     : {'✅ Connected' if tok_ok else '🔴 No token'}\n"
                f"Algo       : {algo_str}\n"
                f"Deployment : {'✅ Armed' if _deployment else '⏳ Not deployed'}\n"
                f"ATO CE     : {'🔴 Triggered' if _ato['ce'] else '🟢 Idle'}\n"
                f"ATO PE     : {'🔴 Triggered' if _ato['pe'] else '🟢 Idle'}"
            ),
        )
        return

    # ── help / hello / invalid ────────────────────────────────────────────────
    _KAVACH_HELP = (
        "🛡 KAVACH — Available Commands\n\n"
        "/register        — Register Batman legs (7-step wizard)\n"
        "/ato_status      — ATO running status\n"
        "/ato_report      — ATO cycle report (buy/sell + points)\n"
        "/legs            — Show open Batman legs\n"
        "/funds           — Available margin\n"
        "/pause           — Pause ATO monitoring\n"
        "/resume          — Resume ATO monitoring\n"
        "/start_algo_now  — Start algo immediately\n"
        "/batman_complete — Mark Batman done (full cleanup)\n"
        "/exit            — Emergency exit all positions\n"
        "/status          — System status"
    )

    if t.lower() in ("hello", "hi", "/start"):
        _bot("kavach", "🛡 Hello! I'm KAVACH, your trading control bot.\n\n" + _KAVACH_HELP)
        return

    _bot("kavach", f"❌ Invalid command: {t}\n\n" + _KAVACH_HELP)


def _show_ato() -> None:
    if not _deployment:
        _bot("kavach", "⚠️ No deployment registered. Run /register first.")
        return
    ato = _deployment["ato"]
    ce_entry_buffer = int(ato.get("ce_entry_buffer_points", 0))
    pe_entry_buffer = int(ato.get("pe_entry_buffer_points", 0))
    ce_trigger = int(ato.get("ce_sell_strike", 0)) + ce_entry_buffer
    pe_trigger = int(ato.get("pe_sell_strike", 0)) - pe_entry_buffer
    ce_margin = ce_trigger - _nifty_spot
    pe_margin = _nifty_spot - pe_trigger
    sides = _deployment.get("ato_manage_sides", "both")
    sides_label = {"pe": "PE side only 🔻", "ce": "CE side only 🔺", "both": "Both sides ⚡"}
    _bot(
        "kavach",
        (
            f"🛡 ATO Status  |  NIFTY: ₹{_nifty_spot:,.2f}\n"
            f"{'─'*42}\n"
            f"CE side : {'🔴 TRIGGERED' if _ato['ce'] else '🟢 IDLE'}\n"
            f"  Symbol  : {ato['ce_protect_symbol']}\n"
            f"  Fires  ≥: {ce_trigger:,} pts  |  Margin: {ce_margin:+.0f} pts\n\n"
            f"PE side : {'🔴 TRIGGERED' if _ato['pe'] else '🟢 IDLE'}\n"
            f"  Symbol  : {ato['pe_protect_symbol']}\n"
            f"  Fires  ≤: {pe_trigger:,} pts  |  Margin: {pe_margin:+.0f} pts\n"
            f"{'─'*42}\n"
            f"CE cycles: {_ato['ce_cycles']}/{_ato['max_cycles']}\n"
            f"PE cycles: {_ato['pe_cycles']}/{_ato['max_cycles']}\n"
            f"{'─'*42}\n"
            f"Entry buffer: CE +{ce_entry_buffer} / PE -{pe_entry_buffer} pts\n"
            f"Retrace    : {_deployment.get('retrace_points', 20)} pts\n"
            f"{'─'*42}\n"
            f"🤖 Algo manages: {sides_label.get(sides, sides)}"
        ),
        mono=True,
    )


# ── Wizard (side-scoped — parity with KAVACH register_wizard) ─────────────────


def _sim_lot_size() -> int:
    return _NIFTY_LOT_SIZE


def _sim_pos_label(p: dict) -> str:
    qty = abs(int(p["qty"]))
    lots = qty_to_lots(qty, _sim_lot_size())
    return f"{p['symbol']}  |  {p['direction']} {qty} qty ({lots} lots)  |  avg ₹{p['avg']:.2f}"


def _sim_pos_keyboard(positions: list[dict], available: list[int]) -> list[list[dict]]:
    rows = []
    for i in available:
        rows.append([{"text": _sim_pos_label(positions[i]), "data": f"wizard:leg:{i}"}])
    return rows


def _sim_lots_keyboard(side: str, max_lots: int) -> list[list[dict]]:
    rows: list[list[dict]] = []
    row: list[dict] = []
    for n in range(1, max_lots + 1):
        row.append({"text": str(n), "data": f"wizard:lots:{side}:{n}"})
        if len(row) >= 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": f"Use all ({max_lots})", "data": f"wizard:lots:{side}:all"}])
    rows.append([{"text": "❌  Cancel", "data": "wizard:cancel"}])
    return rows


def _wizard_begin() -> None:
    global _wizard
    positions = _sorted_positions()
    _wizard = {
        "step": "pe_intent",
        "all": positions,
        "available": list(range(len(positions))),
        "pe_enabled": None,
        "ce_enabled": None,
        "pe_buy": None,
        "pe_sell": None,
        "ce_buy": None,
        "ce_sell": None,
        "pe_managed_lots": None,
        "ce_managed_lots": None,
    }
    _bot(
        "kavach",
        "📡 Fetching your open NIFTY positions from Dhan…",
    )
    time.sleep(0.35)
    _bot(
        "kavach",
        "Enable PE side coverage?",
        keyboard=[
            [
                {"text": "Enable PE", "data": "wizard:side:pe:enable"},
                {"text": "Skip PE", "data": "wizard:side:pe:skip"},
            ],
            [{"text": "❌  Cancel", "data": "wizard:cancel"}],
        ],
    )


def _wizard_start() -> None:
    global _wizard
    if _deployment:
        _wizard = {"step": "pre_confirm"}
        _bot(
            "kavach",
            "⚠️ Batman is currently ARMED.\n\n"
            "Running /register will pause ATO monitoring during the wizard.\n"
            "If you cancel mid-wizard, Batman will NOT be re-armed automatically.\n\n"
            "Continue?",
            keyboard=[
                [
                    {"text": "✅  Yes — start wizard", "data": "wizard:pre_confirm"},
                    {"text": "❌  Cancel — keep current", "data": "wizard:abort"},
                ]
            ],
        )
        return
    _wizard_begin()


def _wizard_pe_buy_step() -> None:
    positions = _wizard["all"]
    pool = [
        i
        for i in _wizard["available"]
        if positions[i]["optType"] == "PUT" and positions[i]["direction"] == "LONG"
    ]
    _wizard["_pick_pool"] = pool
    _wizard["step"] = "pe_buy"
    kb = _sim_pos_keyboard(positions, pool)
    kb.append([{"text": "❌  Cancel", "data": "wizard:cancel"}])
    _bot("kavach", "Select PE BUY leg (LONG PE):", keyboard=kb)


def _wizard_pe_sell_step() -> None:
    positions = _wizard["all"]
    used = {_wizard["pe_buy"]["symbol"]}
    pool = [
        i
        for i in _wizard["available"]
        if positions[i]["optType"] == "PUT"
        and positions[i]["direction"] == "SHORT"
        and positions[i]["symbol"] not in used
    ]
    _wizard["_pick_pool"] = pool
    _wizard["step"] = "pe_sell"
    kb = _sim_pos_keyboard(positions, pool)
    kb.append([{"text": "❌  Cancel", "data": "wizard:cancel"}])
    _bot(
        "kavach",
        f"✅ PE BUY: {_wizard['pe_buy']['symbol']}\n\nSelect PE SELL leg (SHORT PE):",
        keyboard=kb,
    )


def _wizard_pe_lots_step() -> None:
    lot_size = _sim_lot_size()
    buy_qty = abs(int(_wizard["pe_buy"]["qty"]))
    sell_qty = abs(int(_wizard["pe_sell"]["qty"]))
    max_l, buy_l, sell_l, lot_size = side_lots_selection(buy_qty, sell_qty, lot_size=lot_size)
    _wizard["_pe_max_lots"] = max_l
    _wizard["step"] = "pe_lots"
    _bot(
        "kavach",
        (
            f"PE side — select lots to manage\n"
            f"BUY {buy_qty} qty ({buy_l} lots) · SELL {sell_qty} qty ({sell_l} lots)\n"
            f"NIFTY lot size {lot_size} · max {max_l} lots:"
        ),
        keyboard=_sim_lots_keyboard("pe", max_l),
    )


def _wizard_ce_intent_step() -> None:
    _wizard["step"] = "ce_intent"
    _bot(
        "kavach",
        "Enable CE side coverage?",
        keyboard=[
            [
                {"text": "Enable CE", "data": "wizard:side:ce:enable"},
                {"text": "Skip CE", "data": "wizard:side:ce:skip"},
            ],
            [{"text": "❌  Cancel", "data": "wizard:cancel"}],
        ],
    )


def _wizard_ce_buy_step() -> None:
    positions = _wizard["all"]
    pool = [
        i
        for i in _wizard["available"]
        if positions[i]["optType"] == "CALL" and positions[i]["direction"] == "LONG"
    ]
    _wizard["_pick_pool"] = pool
    _wizard["step"] = "ce_buy"
    kb = _sim_pos_keyboard(positions, pool)
    kb.append([{"text": "❌  Cancel", "data": "wizard:cancel"}])
    _bot("kavach", "Select CE BUY leg (LONG CE):", keyboard=kb)


def _wizard_ce_sell_step() -> None:
    positions = _wizard["all"]
    used = {_wizard["ce_buy"]["symbol"]}
    pool = [
        i
        for i in _wizard["available"]
        if positions[i]["optType"] == "CALL"
        and positions[i]["direction"] == "SHORT"
        and positions[i]["symbol"] not in used
    ]
    _wizard["_pick_pool"] = pool
    _wizard["step"] = "ce_sell"
    kb = _sim_pos_keyboard(positions, pool)
    kb.append([{"text": "❌  Cancel", "data": "wizard:cancel"}])
    _bot(
        "kavach",
        f"✅ CE BUY: {_wizard['ce_buy']['symbol']}\n\nSelect CE SELL leg (SHORT CE):",
        keyboard=kb,
    )


def _wizard_ce_lots_step() -> None:
    lot_size = _sim_lot_size()
    buy_qty = abs(int(_wizard["ce_buy"]["qty"]))
    sell_qty = abs(int(_wizard["ce_sell"]["qty"]))
    max_l, buy_l, sell_l, lot_size = side_lots_selection(buy_qty, sell_qty, lot_size=lot_size)
    _wizard["_ce_max_lots"] = max_l
    _wizard["step"] = "ce_lots"
    _bot(
        "kavach",
        (
            f"CE side — select lots to manage\n"
            f"BUY {buy_qty} qty ({buy_l} lots) · SELL {sell_qty} qty ({sell_l} lots)\n"
            f"NIFTY lot size {lot_size} · max {max_l} lots:"
        ),
        keyboard=_sim_lots_keyboard("ce", max_l),
    )


def _wizard_apply_lots(side: str, lots: int) -> None:
    lot_size = _sim_lot_size()
    if side == "pe":
        buy, sell = scale_side_flexible(
            _wizard["pe_buy"], _wizard["pe_sell"], lots, lot_size=lot_size
        )
        _wizard["pe_buy"] = buy
        _wizard["pe_sell"] = sell
        _wizard["pe_managed_lots"] = lots
        _wizard_ce_intent_step()
    else:
        buy, sell = scale_side_flexible(
            _wizard["ce_buy"], _wizard["ce_sell"], lots, lot_size=lot_size
        )
        _wizard["ce_buy"] = buy
        _wizard["ce_sell"] = sell
        _wizard["ce_managed_lots"] = lots
        _wizard["step"] = "entry_buffer"
        _wizard_entry_buffer_step()


def _wizard_leg_pick(idx: int) -> None:
    if not _wizard:
        return
    positions = _wizard["all"]
    pool = _wizard.get("_pick_pool") or []
    if idx >= len(pool):
        return
    real_idx = pool[idx]
    p = positions[real_idx]
    step = _wizard.get("step")
    if step == "pe_buy":
        _wizard["pe_buy"] = p
        _wizard["available"].remove(real_idx)
        _wizard_pe_sell_step()
    elif step == "pe_sell":
        _wizard["pe_sell"] = p
        _wizard["available"].remove(real_idx)
        _wizard_pe_lots_step()
    elif step == "ce_buy":
        _wizard["ce_buy"] = p
        _wizard["available"].remove(real_idx)
        _wizard_ce_sell_step()
    elif step == "ce_sell":
        _wizard["ce_sell"] = p
        _wizard["available"].remove(real_idx)
        _wizard_ce_lots_step()


def _wizard_step1() -> None:
    """Legacy alias — start side-scoped wizard."""
    _wizard_begin()


def _sorted_positions() -> list[dict]:
    """Return mock positions sorted by strike ascending."""
    result = []
    for row in _RAW_POSITIONS:
        direction = "LONG" if row["netQty"] > 0 else "SHORT"
        qty = abs(int(row["netQty"]))
        avg = row["buyAvg"] if row["netQty"] > 0 else row["sellAvg"]
        result.append(
            {
                "symbol": row["symbol"],
                "direction": direction,
                "qty": qty,
                "avg": avg,
                "optType": row["drvOptionType"],
                "strike": int(row["drvStrikePrice"]),
                "expiry": row["drvExpiryDate"],
            }
        )
    result.sort(key=lambda x: x["strike"])
    return result


def _pos_keyboard(positions: list[dict], available: list[int]) -> list[list[dict]]:
    """Deprecated — use _sim_pos_keyboard."""
    return _sim_pos_keyboard(positions, available)


def _wizard_select(idx: int) -> None:
    """Deprecated — use _wizard_leg_pick."""
    _wizard_leg_pick(idx)


def _entry_buffer_keyboard() -> list[list[dict]]:
    return [
        [
            {"text": "0 pts", "data": "wizard:entrybuf:0"},
            {"text": "5 pts", "data": "wizard:entrybuf:5"},
            {"text": "10 pts", "data": "wizard:entrybuf:10"},
        ],
        [
            {"text": "15 pts", "data": "wizard:entrybuf:15"},
            {"text": "20 pts", "data": "wizard:entrybuf:20"},
        ],
        [{"text": "❌  Cancel", "data": "wizard:cancel"}],
    ]


def _wizard_entry_buffer_step() -> None:
    if not _wizard.get("pe_enabled") and not _wizard.get("ce_enabled"):
        _bot("kavach", "⚠️ Select at least one side (PE or CE).")
        return
    ps = _wizard.get("pe_sell") or {"strike": 0}
    cs = _wizard.get("ce_sell") or {"strike": 0}
    _bot(
        "kavach",
        (
            "Step 5/7 — Entry Buffer (Trigger Cushion)\n\n"
            "Choose how many points outside sell strike are required before ATO triggers.\n\n"
            "Example if you choose 5 pts:\n"
            f"  CE trigger = {cs['strike']:,} + 5 = {cs['strike'] + 5:,}\n"
            f"  PE trigger = {ps['strike']:,} - 5 = {ps['strike'] - 5:,}\n\n"
            "This is trigger-only. Retrace exit is configured in the next step."
        ),
        keyboard=_entry_buffer_keyboard(),
    )


def _wizard_retrace_step() -> None:
    """Step — ask user to choose the ATO retrace exit buffer."""
    ps = _wizard.get("pe_sell") or {"strike": 0}
    cs = _wizard.get("ce_sell") or {"strike": 0}
    entry_buffer = int(_wizard.get("entry_buffer_points", 0))
    ce_trigger = cs["strike"] + entry_buffer
    pe_trigger = ps["strike"] - entry_buffer
    header_parts = []
    if _wizard.get("pe_enabled"):
        header_parts.append(f"✅ PE BUY : {_wizard['pe_buy']['symbol']}")
        header_parts.append(f"✅ PE SELL: {_wizard['pe_sell']['symbol']}")
    if _wizard.get("ce_enabled"):
        header_parts.append(f"✅ CE BUY : {_wizard['ce_buy']['symbol']}")
        header_parts.append(f"✅ CE SELL: {_wizard['ce_sell']['symbol']}")
    header_parts.append(f"✅ Entry buffer: {entry_buffer} pts")
    header = "\n".join(header_parts)
    _bot(
        "kavach",
        (
            f"{header}\n"
            f"Step 6/7 — Select ATO retrace points:\n\n"
            f"ATO trigger levels with this entry buffer:\n"
            f"  CE trigger at NIFTY ≥ {ce_trigger:,}\n"
            f"  PE trigger at NIFTY ≤ {pe_trigger:,}\n\n"
            f"It EXITS only when NIFTY pulls back by these many points inside the sell strike.\n\n"
            f"Example: if you choose 20 pts —\n"
            f"  PE ATO exits when NIFTY ≥ {ps['strike']:,} + 20 = {ps['strike']+20:,}\n"
            f"  CE ATO exits when NIFTY ≤ {cs['strike']:,} − 20 = {cs['strike']-20:,}\n\n"
            f"Select retrace buffer:"
        ),
        keyboard=[
            [
                {"text": "0 pts (exit now)", "data": "wizard:retrace:0"},
                {"text": "5 pts", "data": "wizard:retrace:5"},
                {"text": "10 pts", "data": "wizard:retrace:10"},
                {"text": "15 pts", "data": "wizard:retrace:15"},
            ],
            [
                {"text": "20 pts", "data": "wizard:retrace:20"},
                {"text": "25 pts", "data": "wizard:retrace:25"},
                {"text": "30 pts", "data": "wizard:retrace:30"},
                {"text": "35 pts", "data": "wizard:retrace:35"},
            ],
            [
                {"text": "40 pts", "data": "wizard:retrace:40"},
                {"text": "45 pts", "data": "wizard:retrace:45"},
                {"text": "50 pts", "data": "wizard:retrace:50"},
            ],
            [{"text": "❌  Cancel", "data": "wizard:cancel"}],
        ],
    )


def _wizard_ato_monitor_step() -> None:
    """Ask which ATO sides the algo should auto-manage."""
    ps = _wizard.get("pe_sell") or {"strike": 0}
    cs = _wizard.get("ce_sell") or {"strike": 0}
    entry_buffer = int(_wizard.get("entry_buffer_points", 0))
    ce_trigger = cs["strike"] + entry_buffer
    pe_trigger = ps["strike"] - entry_buffer
    retrace_pts = _wizard.get("retrace_points", 20)
    pe_ato_strike = ps["strike"] - 50 if _wizard.get("pe_enabled") else 0
    ce_ato_strike = cs["strike"] + 50 if _wizard.get("ce_enabled") else 0
    lines = ["ATO Monitoring Mode\n"]
    if _wizard.get("pe_enabled"):
        lines.append(f"  PE ATO: {pe_ato_strike:,}  (fires when NIFTY ≤ {pe_trigger:,})")
    if _wizard.get("ce_enabled"):
        lines.append(f"  CE ATO: {ce_ato_strike:,}  (fires when NIFTY ≥ {ce_trigger:,})")
    lines.extend(
        [
            f"\nEntry buffer: {entry_buffer} pts",
            f"Retrace buffer: {retrace_pts} pts\n",
            "Which side(s) should the algo automatically manage?",
        ]
    )
    kb: list[list[dict]] = []
    if _wizard.get("pe_enabled"):
        kb.append([{"text": "PE side only", "data": "wizard:ato_monitor:pe"}])
    if _wizard.get("ce_enabled"):
        if kb:
            kb[0].append({"text": "CE side only", "data": "wizard:ato_monitor:ce"})
        else:
            kb.append([{"text": "CE side only", "data": "wizard:ato_monitor:ce"}])
    if _wizard.get("pe_enabled") and _wizard.get("ce_enabled"):
        kb.append([{"text": "Both sides (recommended)", "data": "wizard:ato_monitor:both"}])
    kb.append([{"text": "❌  Cancel", "data": "wizard:cancel"}])
    _bot("kavach", "\n".join(lines), keyboard=kb)


def _wizard_summary() -> None:
    global _wizard
    pb = _wizard.get("pe_buy")
    ps = _wizard.get("pe_sell")
    cb = _wizard.get("ce_buy")
    cs = _wizard.get("ce_sell")

    pe_ato_strike = ps["strike"] - 50 if ps else 0
    ce_ato_strike = cs["strike"] + 50 if cs else 0

    pe_ato_sym = ce_ato_sym = ""
    if ps:
        m_pe = re.match(r"([A-Z]+\d+[A-Z]+)", ps["symbol"])
        pe_prefix = m_pe.group(1) if m_pe else "NIFTY07APR"
        pe_ato_sym = f"{pe_prefix}{pe_ato_strike}PE"
    if cs:
        m_ce = re.match(r"([A-Z]+\d+[A-Z]+)", cs["symbol"])
        ce_prefix = m_ce.group(1) if m_ce else "NIFTY07APR"
        ce_ato_sym = f"{ce_prefix}{ce_ato_strike}CE"

    entry_buffer = int(_wizard.get("entry_buffer_points", 0))
    ce_trigger = (cs["strike"] + entry_buffer) if cs else 0
    pe_trigger = (ps["strike"] - entry_buffer) if ps else 0

    _wizard["ato"] = {
        "pe_protect_symbol": pe_ato_sym or None,
        "pe_protect_strike": pe_ato_strike or None,
        "ce_protect_symbol": ce_ato_sym or None,
        "ce_protect_strike": ce_ato_strike or None,
        "ce_entry_buffer_points": entry_buffer,
        "pe_entry_buffer_points": entry_buffer,
        "ato_step": 50,
        "retrace_points": _wizard.get("retrace_points", 20),
    }

    sides = _wizard.get("ato_manage_sides", "both")
    sides_label = {
        "pe": "PE side only",
        "ce": "CE side only",
        "both": "Both sides (recommended)",
    }
    summary_lines = ["🦇 Batman Position Summary", "─" * 44]
    if pb and ps:
        summary_lines.append(
            f"PE BUY  : {pb['symbol']:<24} qty={pb['qty']:<6} lots={_wizard.get('pe_managed_lots')} avg=₹{pb['avg']:.2f}"
        )
        summary_lines.append(
            f"PE SELL : {ps['symbol']:<24} qty={ps['qty']:<6} avg=₹{ps['avg']:.2f}"
        )
    if cb and cs:
        summary_lines.append(
            f"CE BUY  : {cb['symbol']:<24} qty={cb['qty']:<6} lots={_wizard.get('ce_managed_lots')} avg=₹{cb['avg']:.2f}"
        )
        summary_lines.append(
            f"CE SELL : {cs['symbol']:<24} qty={cs['qty']:<6} avg=₹{cs['avg']:.2f}"
        )
    summary_lines.extend(["─" * 44, f"ATO monitoring: {sides_label.get(sides, sides)}"])
    if cs:
        summary_lines.append(f"  CE trigger at NIFTY ≥ {ce_trigger:,}")
    if ps:
        summary_lines.append(f"  PE trigger at NIFTY ≤ {pe_trigger:,}")
    summary = "\n".join(summary_lines)
    _bot(
        "kavach",
        summary,
        keyboard=[
            [
                {"text": "✅  Confirm & Arm Batman", "data": "wizard:confirm"},
                {"text": "❌  Cancel & Start Over", "data": "wizard:cancel"},
            ]
        ],
        mono=True,
    )


def _wizard_confirm() -> None:
    global _wizard, _deployment, _algo_running
    ato = _wizard["ato"]
    retrace_pts = ato.get("retrace_points", 20)
    ce_entry_buffer = int(ato.get("ce_entry_buffer_points", 0))
    pe_entry_buffer = int(ato.get("pe_entry_buffer_points", 0))
    _now = datetime.now()
    _now_str = _now.strftime("%Y-%m-%d_%H-%M")

    def _leg(key: str) -> dict | None:
        leg = _wizard.get(key)
        if not leg:
            return None
        return {
            "symbol": leg["symbol"],
            "strike": leg["strike"],
            "qty": leg["qty"],
            "avg_price": leg["avg"],
            "broker_qty": leg.get("broker_qty", leg["qty"]),
        }

    _deployment = {
        "deployed_at": _now.isoformat(),
        "registered_at": _now.strftime("%A %d-%b-%Y at %H:%M"),
        "file_name": f"batman_{_now_str}.json",
        "positions": {
            "pe_buy": _leg("pe_buy"),
            "pe_sell": _leg("pe_sell"),
            "ce_sell": _leg("ce_sell"),
            "ce_buy": _leg("ce_buy"),
        },
        "registration_scope": {
            "pe_enabled": bool(_wizard.get("pe_enabled")),
            "ce_enabled": bool(_wizard.get("ce_enabled")),
            "pe_managed_lots": _wizard.get("pe_managed_lots"),
            "ce_managed_lots": _wizard.get("ce_managed_lots"),
            "lot_size": _sim_lot_size(),
        },
        "ato": ato,
        "retrace_points": retrace_pts,
        "ato_manage_sides": _wizard.get("ato_manage_sides", "both"),
        "status": "armed",
    }
    _algo_running = True
    _wizard = None
    ps = _deployment["positions"].get("pe_sell") or {"strike": 0}
    cs = _deployment["positions"].get("ce_sell") or {"strike": 0}
    _bot(
        "kavach",
        (
            f"✅ Batman armed. KAVACH is watching.\n\n"
            f"File: {_deployment['file_name']}\n\n"
            f"🛡 ATO protection:\n"
            f"  PE fires when NIFTY ≤ {ps['strike']-pe_entry_buffer:,}  (buffer {pe_entry_buffer} pts → ATO at {ato['pe_protect_strike']:,})\n"
            f"  CE fires when NIFTY ≥ {cs['strike']+ce_entry_buffer:,}  (buffer {ce_entry_buffer} pts → ATO at {ato['ce_protect_strike']:,})\n"
            f"  Retrace exit: {retrace_pts} pts\n\n"
            f"  Current NIFTY: ₹{_nifty_spot:,.0f}\n"
            f"  Margin to PE trigger:  {_nifty_spot - (ps['strike']-pe_entry_buffer):,.0f} pts  🟢\n"
            f"  Margin to CE trigger:  {(cs['strike']+ce_entry_buffer) - _nifty_spot:,.0f} pts  🟢\n\n"
            f"⏰ Use /start_algo_now to begin ATO monitoring immediately."
        ),
    )


def _do_batman_complete() -> None:
    global _deployment, _algo_running, _algo_paused, _batman_complete_pending, _ato

    reg_at = _deployment.get("registered_at", "unknown") if _deployment else "unknown"
    file_name = _deployment.get("file_name", "unknown") if _deployment else "unknown"
    done_at = _sim_time.strftime("%A %d-%b-%Y at %H:%M")

    _deployment = None
    _algo_running = False
    _algo_paused = False
    _ato = {"ce": False, "pe": False, "ce_cycles": 0, "pe_cycles": 0, "max_cycles": 3}
    _batman_complete_pending = False

    dir_ok, checks = verify_batman_cleanup(deploy_dir=_SIM_DEPLOY_DIR, state_get=None)
    checks.extend(
        [
            ("In-memory deployment cleared", _deployment is None),
            ("Algo monitoring stopped", not _algo_running),
            ("ATO state reset", not _ato["ce"] and not _ato["pe"]),
        ]
    )
    all_ok = dir_ok and all(ok for _, ok in checks)

    body = format_cleanup_verification_message(
        all_ok=all_ok,
        checks=checks,
        registered_at=reg_at,
        completed_at=done_at,
        archived_file=file_name,
    )
    _bot("kavach", body.replace("\\-", "-").replace("\\.", "."))


def _do_emergency_exit() -> None:
    global _deployment, _algo_running, _algo_paused, _exit_pending, _ato
    p = _deployment["positions"] if _deployment else {}
    _bot(
        "kavach",
        (
            "🚨 Emergency Exit — Placing market orders:\n\n"
            f"  {p.get('pe_buy',  {}).get('symbol','?')}  SELL MKT\n"
            f"  {p.get('pe_sell', {}).get('symbol','?')}  BUY  MKT\n"
            f"  {p.get('ce_sell', {}).get('symbol','?')}  BUY  MKT\n"
            f"  {p.get('ce_buy',  {}).get('symbol','?')}  SELL MKT"
        ),
    )
    time.sleep(0.6)
    _deployment = None
    _algo_running = False
    _algo_paused = False
    _ato = {"ce": False, "pe": False, "ce_cycles": 0, "pe_cycles": 0, "max_cycles": 3}
    _exit_pending = False
    _bot(
        "kavach",
        (
            "🚨 Emergency Exit executed.\n\n"
            "All positions closed at market.\n"
            "Algo reset — deploy fresh via /register when ready."
        ),
    )
    # LAKSHMI push omitted (deferred phase)


def _handle_sanchalak(text: str) -> None:
    global _global_enabled, _runtime_mode, _algo_running, _algo_paused
    t = text.strip()
    parts = t.split()
    cmd = parts[0].lower() if parts else ""

    if cmd == "/status_all":
        paused = [k.upper() for k, v in _paused_bots.items() if v]
        _bot(
            "sanchalak",
            (
                "🎛 SANCHALAK Status\n\n"
                f"Global enabled : {'✅ YES' if _global_enabled else '⛔ NO'}\n"
                f"Runtime mode   : {_runtime_mode.upper()}\n"
                f"Algo state     : {'⏸ Paused' if _algo_paused else ('▶ Running' if _algo_running else '⏳ Idle')}\n"
                f"Paused bots    : {', '.join(paused) if paused else 'None'}"
            ),
        )
        return

    if cmd == "/start_all":
        _global_enabled = True
        _algo_paused = False
        _algo_running = _algo_running or (_deployment is not None)
        _bot("sanchalak", "✅ Global controls started. Action commands are enabled.")
        return

    if cmd == "/stop_all":
        _global_enabled = False
        _algo_paused = True
        _bot(
            "sanchalak",
            "🛑 Global controls stopped. All action commands are blocked until /start_all.",
        )
        return

    if cmd == "/pause_bot":
        if len(parts) < 2:
            _bot("sanchalak", "Usage: /pause_bot <drishti|kavach|saransh|jagran>")
            return
        target = parts[1].lower()
        if not _set_bot_paused(target, True):
            _bot("sanchalak", f"❌ Unknown bot: {target}")
            return
        _bot("sanchalak", f"⏸ {target.upper()} paused. Read-only commands remain allowed.")
        return

    if cmd == "/resume_bot":
        if len(parts) < 2:
            _bot("sanchalak", "Usage: /resume_bot <drishti|kavach|saransh|jagran>")
            return
        target = parts[1].lower()
        if not _set_bot_paused(target, False):
            _bot("sanchalak", f"❌ Unknown bot: {target}")
            return
        _bot("sanchalak", f"▶ {target.upper()} resumed.")
        return

    if cmd == "/set_mode":
        if len(parts) < 2:
            _bot("sanchalak", "Usage: /set_mode <mock|live>")
            return
        mode = parts[1].lower()
        if mode not in {"mock", "live"}:
            _bot("sanchalak", "❌ Invalid mode. Use mock or live.")
            return
        _runtime_mode = mode
        _bot("sanchalak", f"✅ Runtime mode set to {mode.upper()}.")
        return

    if t.lower() in ("hello", "hi", "/start"):
        _bot(
            "sanchalak",
            (
                "🎛 SANCHALAK control plane\n\n"
                "/start_all\n"
                "/stop_all\n"
                "/pause_bot <drishti|kavach|saransh|jagran>\n"
                "/resume_bot <drishti|kavach|saransh|jagran>\n"
                "/set_mode <mock|live>\n"
                "/status_all"
            ),
        )
        return

    _bot("sanchalak", f"❌ Invalid command: {t}\n\nUse /status_all to view controls.")


def _handle_saransh(text: str) -> None:
    t = text.strip()
    cmd = _command_name(t)

    if _blocked_by_controls("saransh", cmd):
        return

    if t in ("/summary", "/summary_eod"):
        pnl = _calc_pnl()
        pnl_line = "No active deployment" if pnl is None else f"₹{pnl:+,.2f}"
        _bot(
            "saransh",
            (
                f"📘 SARANSH Summary ({_sim_time.strftime('%d-%b %H:%M IST')})\n\n"
                f"Runtime mode  : {_runtime_mode.upper()}\n"
                f"Deployment    : {'✅ Armed' if _deployment else '⏳ None'}\n"
                f"Algo          : {'⏸ Paused' if _algo_paused else ('▶ Running' if _algo_running else '⏳ Idle')}\n"
                f"NIFTY         : ₹{_nifty_spot:,.2f}\n"
                f"PnL (sim)     : {pnl_line}\n"
                f"ATO CE cycles : {_ato['ce_cycles']}\n"
                f"ATO PE cycles : {_ato['pe_cycles']}"
            ),
        )
        return

    if t == "/status":
        _bot(
            "saransh",
            (
                "📌 SARANSH Status\n\n"
                f"Paused         : {'YES' if _paused_bots['saransh'] else 'NO'}\n"
                f"Global enabled : {'YES' if _global_enabled else 'NO'}\n"
                f"Mode           : {_runtime_mode.upper()}"
            ),
        )
        return

    if t.lower() in ("hello", "hi", "/start"):
        _bot("saransh", "📘 SARANSH\n\n/summary\n/summary_eod\n/status")
        return

    _bot("saransh", f"❌ Invalid command: {t}\n\nUse /summary or /status.")


def _handle_jagran(text: str) -> None:
    t = text.strip()
    cmd = _command_name(t)

    if _blocked_by_controls("jagran", cmd):
        return

    if t == "/status":
        _bot(
            "jagran",
            (
                "🚨 JAGRAN Status\n\n"
                f"Mode           : {_runtime_mode.upper()}\n"
                f"Global enabled : {'YES' if _global_enabled else 'NO'}\n"
                f"Token          : {'present' if (_sim_token_saved_at is not None or _token_store.load()[0] is not None) else 'missing'}\n"
                f"Last events    : {len(_algo_events)}"
            ),
        )
        return

    if t == "/recent":
        recent = _algo_events[-5:]
        if not recent:
            _bot("jagran", "No recent incidents in simulator.")
            return
        lines = [f"{e['time_str']} [{e['level'].upper()}] {e['msg']}" for e in recent]
        _bot("jagran", "🚨 Recent incidents\n\n" + "\n".join(lines), mono=True)
        return

    if t.lower() in ("hello", "hi", "/start"):
        _bot("jagran", "🚨 JAGRAN\n\n/status\n/recent")
        return

    _bot("jagran", f"❌ Invalid command: {t}\n\nUse /status or /recent.")


# ═══════════════════════════════════════════════════════════════════════════════
# Deferred: LAKSHMI — MTM & P&L  (re-enable when LAKSHMI bot is live)
# Helper retained: _calc_pnl() + _pnl_table() — used by api/state route
# ═══════════════════════════════════════════════════════════════════════════════


def _calc_pnl() -> float | None:
    if not _deployment:
        return None
    # Approximation: base real P&L ± NIFTY movement impact
    base = 14878.50
    spot_diff = _nifty_spot - 22713.0
    return round(base + spot_diff * 0.5, 2)


def _pnl_table() -> str:
    pnl = _calc_pnl()
    if pnl is None:
        return "No active deployment."
    sign = "🟢" if pnl >= 0 else "🔴"
    ato_str = "🔴 CE TRIGGERED" if _ato["ce"] else ("🔴 PE TRIGGERED" if _ato["pe"] else "🟢 IDLE")
    return (
        f"📊 MTM — {datetime.now().strftime('%d-%b-%Y · %H:%M IST')}\n"
        f"NIFTY Spot: ₹{_nifty_spot:,.2f}\n"
        f"{'─'*40}\n"
        f"Leg             LTP     Avg     P&L\n"
        f"{'─'*40}\n"
        f"PE BUY  22050   79.05   95.19  -12,587 🔴\n"
        f"PE SELL 22000   72.00   87.00  +23,400 🟢\n"
        f"CE SELL 23200   71.10   76.00   +7,644 🟢\n"
        f"CE BUY  23150   83.50   88.09   -3,578 🔴\n"
        f"{'─'*40}\n"
        f"💰 Total P&L : ₹{pnl:+,.2f}  {sign}\n"
        f"{'─'*40}\n"
        f"ATO: {ato_str}"
    )


def _handle_lakshmi(_text: str) -> None:
    pass


# ── Background MTM thread — DEFERRED (LAKSHMI deactivated) ───────────────────
# def _mtm_thread() -> None:
#     while True:
#         time.sleep(60)
#         if _algo_running and not _algo_paused and _deployment:
#             pnl = _calc_pnl()
#             if pnl is not None:
#                 sign = "🟢" if pnl >= 0 else "🔴"
#                 _bot("lakshmi", (
#                     f"📊 Auto-MTM — {datetime.now().strftime('%H:%M IST')}\n"
#                     f"NIFTY: ₹{_nifty_spot:,.2f}  |  P&L: ₹{pnl:+,.2f} {sign}"
#                 ))
# threading.Thread(target=_mtm_thread, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
# KEYBOARD CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════════════════════


def _handle_keyboard(bot: str, data: str) -> None:
    global _wizard, _deployment, _batman_complete_pending, _exit_pending, _awaiting_token_drishti

    # ── DRISHTI main menu callbacks ───────────────────────────────────────────
    if data.startswith("drishti:menu:"):
        action = data.rsplit(":", 1)[-1]
        if action == "health":
            _handle_drishti("/health")
        elif action == "status":
            _handle_drishti("/status")
        elif action == "update_token":
            _handle_drishti("/update_token")
        elif action == "deactivate_token":
            _handle_drishti("/deactivate_token")
        elif action == "ping":
            _handle_drishti("/ping")
        elif action == "nifty_ltp_polling":
            _handle_drishti("/nifty_ltp")
        elif action == "nifty_ltp_ws":
            _bot(
                "drishti",
                (
                    f"📈 NIFTY LTP (WebSocket)\n\n"
                    f"Price : ₹{_nifty_spot:,.2f}\n"
                    f"Source: WebSocket — one-shot health test\n"
                    f"As of : {_sim_time.strftime('%H:%M IST')}\n\n"
                    "✅ WebSocket path OK (sim). KAVACH/ATO uses Polling feed."
                ),
                keyboard=_drishti_main_menu_keyboard(),
            )
        elif action == "ltp_setup":
            _bot(
                "drishti",
                "⚙️ LTP Feed Setup\n\n"
                "Configure NIFTY LTP (Polling) interval and stale threshold.\n"
                "(Full wizard in live DRISHTI — use LTP Feed Setup button there.)",
                keyboard=_drishti_main_menu_keyboard(),
            )
        return

    if data == "reminder_yes":
        _awaiting_token_drishti = True
        _bot(
            "drishti",
            "\U0001f504 Update Dhan Access Token\n\n"
            "Please paste your fresh Dhan JWT access token now.\n"
            "Get it from: web.dhan.co \u2192 Profile \u2192 Access DhanHQ APIs",
        )
        return
    if data == "reminder_no":
        _bot(
            "drishti",
            "\u2705 OK \u2014 I'll remind you at the next scheduled time.\n\n"
            "Next reminders: 09:00 / 15:30 / 23:00 IST (weekdays only)",
        )
        return

    if data == "wizard:pre_confirm":
        _wizard = None
        _deployment = None
        _wizard_begin()
        return
    if data == "wizard:abort":
        _wizard = None
        _bot("kavach", "✅ Wizard cancelled. Existing deployment unchanged.")
        return
    if data.startswith("wizard:side:pe:"):
        action = data.rsplit(":", 1)[-1]
        if action == "cancel":
            _wizard = None
            _bot("kavach", "❌ Deployment cancelled.")
            return
        if action == "skip":
            _wizard["pe_enabled"] = False
            _wizard_ce_intent_step()
            return
        _wizard["pe_enabled"] = True
        _wizard_pe_buy_step()
        return
    if data.startswith("wizard:side:ce:"):
        action = data.rsplit(":", 1)[-1]
        if action == "cancel":
            _wizard = None
            _bot("kavach", "❌ Deployment cancelled.")
            return
        if action == "skip":
            if not _wizard.get("pe_enabled"):
                _wizard = None
                _bot("kavach", "⚠️ Select at least one side (PE or CE).")
                return
            _wizard["ce_enabled"] = False
            _wizard["step"] = "entry_buffer"
            _wizard_entry_buffer_step()
            return
        _wizard["ce_enabled"] = True
        _wizard_ce_buy_step()
        return
    if data.startswith("wizard:leg:"):
        idx = int(data.rsplit(":", 1)[-1])
        _wizard_leg_pick(idx)
        return
    if data.startswith("wizard:lots:"):
        parts = data.split(":")
        side = parts[2]
        val = parts[3]
        if side == "pe":
            lots = _wizard["_pe_max_lots"] if val == "all" else int(val)
            _wizard_apply_lots("pe", lots)
        else:
            lots = _wizard["_ce_max_lots"] if val == "all" else int(val)
            _wizard_apply_lots("ce", lots)
        return
    if data.startswith("wizard:select:"):
        idx = int(data.rsplit(":", 1)[-1])
        _wizard_leg_pick(idx)
        return
    if data.startswith("wizard:entrybuf:"):
        pts = int(data.rsplit(":", 1)[-1])
        if _wizard and _wizard.get("step") == "entry_buffer":
            _wizard["entry_buffer_points"] = pts
            _wizard["step"] = "retrace"
            _bot("kavach", f"✅ Entry trigger buffer set to {pts} pts (both CE and PE).")
            time.sleep(0.2)
            _wizard_retrace_step()
        return
    if data.startswith("wizard:retrace:"):
        pts = int(data.rsplit(":", 1)[-1])
        if _wizard and _wizard.get("step") == "retrace":
            _wizard["retrace_points"] = pts
            _wizard["step"] = "ato_monitor"
            _bot("kavach", f"✅ Retrace buffer set to {pts} pts.")
            time.sleep(0.2)
            _wizard_ato_monitor_step()
        return
    if data.startswith("wizard:ato_monitor:"):
        side = data.rsplit(":", 1)[-1]
        if _wizard and _wizard.get("step") == "ato_monitor":
            _wizard["ato_manage_sides"] = side
            _wizard["step"] = "summary"
            side_label = {
                "pe": "PE only \U0001f53b",
                "ce": "CE only \U0001f53a",
                "both": "Both sides \u26a1",
            }
            _bot("kavach", f"✅ ATO monitoring: {side_label.get(side, side)}.")
            time.sleep(0.2)
            _wizard_summary()
        return
    if data == "wizard:confirm":
        _wizard_confirm()
        return
    if data == "wizard:cancel":
        _wizard = None
        _bot(
            "kavach",
            ("❌ Deployment cancelled. No file written.\n\n" "Run /register again when ready."),
        )
        return
    if data == "complete:confirm":
        _do_batman_complete()
        return
    if data == "complete:cancel":
        _batman_complete_pending = False
        _bot("kavach", "✅ Cancelled. Deployment unchanged.")
        return
    if data == "exit:confirm":
        threading.Thread(target=_do_emergency_exit, daemon=True).start()
        return
    if data == "exit:cancel":
        _exit_pending = False
        _bot("kavach", "Emergency exit cancelled. Positions unchanged.")
        return


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET SIMULATOR HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _is_sim_market_hours() -> bool:
    """Return True if _sim_time falls within NSE market hours (9:15–15:30 Mon–Fri)."""
    t = _sim_time.time()
    return dt_time(9, 15) <= t <= dt_time(15, 30) and _sim_time.weekday() < 5


def _is_sim_expiry_day() -> bool:
    """Return True if _sim_time is on the deployment's expiry weekday (default Tuesday=1)."""
    expiry_wd = (_deployment or {}).get("expiry_weekday", 1)
    return _sim_time.weekday() == expiry_wd


def _log_algo_event(level: str, msg: str, detail: str = "") -> None:
    """Append an event to the market simulator event log."""
    global _event_id_counter
    _event_id_counter += 1
    _algo_events.append(
        {
            "id": _event_id_counter,
            "date": _sim_time.strftime("%d-%b"),
            "time_str": _sim_time.strftime("%H:%M:%S"),
            "level": level,  # trigger | exit | warn | info | time
            "msg": msg,
            "detail": detail,
        }
    )
    if len(_algo_events) > 300:
        _algo_events.pop(0)


def _ato_side_qty(side: str) -> int:
    if not _deployment:
        return 0
    leg_key = "ce_buy" if side == "CE" else "pe_buy"
    return int(abs(_deployment.get("positions", {}).get(leg_key, {}).get("qty", 0)))


def _record_sim_ato_entry(
    *,
    side: str,
    spot: float,
    sell_strike: int,
    trigger_level: int,
    protect_symbol: str,
    protect_strike: int,
    entry_buffer_points: int,
    retrace_points: int,
) -> None:
    _ato_open_entries[side] = {
        "buy_timestamp_ist": _sim_time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "buy_nifty_ltp": float(spot),
        "sell_strike": int(sell_strike),
        "entry_trigger_level": int(trigger_level),
        "protect_symbol": protect_symbol,
        "protect_strike": int(protect_strike),
        "entry_buffer_points": int(entry_buffer_points),
        "retrace_points": int(retrace_points),
        "qty": _ato_side_qty(side),
    }


def _record_sim_ato_exit(
    *,
    side: str,
    spot: float,
    exit_trigger_level: int,
    exit_order_tag: str,
) -> None:
    entry = _ato_open_entries.get(side)
    if not entry:
        return

    entry_spot = float(entry.get("buy_nifty_ltp", spot))
    points_lost = max(0.0, entry_spot - spot) if side == "CE" else max(0.0, spot - entry_spot)
    qty = int(entry.get("qty", 0))
    dep = _deployment or {}
    lot_size = int(abs(dep.get("positions", {}).get("ce_buy", {}).get("qty", 0)) or 65)
    lots = float(qty) / float(lot_size) if lot_size > 0 else 0.0

    row = {
        "date_ist": _sim_time.strftime("%Y-%m-%d"),
        "timestamp_ist": _sim_time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "side": side,
        "cycle_index": _ato["ce_cycles"] if side == "CE" else _ato["pe_cycles"],
        "buy_timestamp_ist": entry.get("buy_timestamp_ist", ""),
        "buy_nifty_ltp": round(entry_spot, 2),
        "sell_timestamp_ist": _sim_time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "sell_nifty_ltp": round(float(spot), 2),
        "sell_strike": int(entry.get("sell_strike", 0)),
        "entry_trigger_level": int(entry.get("entry_trigger_level", 0)),
        "exit_trigger_level": int(exit_trigger_level),
        "entry_buffer_points": int(entry.get("entry_buffer_points", 0)),
        "retrace_points": int(entry.get("retrace_points", 0)),
        "protect_symbol": entry.get("protect_symbol", ""),
        "protect_strike": int(entry.get("protect_strike", 0)),
        "qty": qty,
        "lots": round(lots, 2),
        "points_lost": round(points_lost, 2),
        "points_lost_x_lots": round(points_lost * lots, 2),
        "exit_order_id": exit_order_tag,
    }
    _ato_trade_ledger.append(row)
    if len(_ato_trade_ledger) > 600:
        _ato_trade_ledger.pop(0)
    _ato_open_entries[side] = None


def _sim_ato_ledger_snapshot() -> dict:
    today = _sim_time.strftime("%Y-%m-%d")
    rows_today = [r for r in _ato_trade_ledger if r.get("date_ist") == today]
    total_points = sum(float(r.get("points_lost", 0.0)) for r in rows_today)
    total_points_x_lots = sum(float(r.get("points_lost_x_lots", 0.0)) for r in rows_today)
    return {
        "date_ist": today,
        "closed_cycles_today": len(rows_today),
        "total_points_lost_today": round(total_points, 2),
        "total_points_lost_x_lots_today": round(total_points_x_lots, 2),
        "rows": _ato_trade_ledger[-12:],
    }


def _auto_check_ato() -> None:
    """Evaluate ATO breach/retrace based on _nifty_spot and _sim_time.

    Fires KAVACH bot messages and logs events on state changes.
    Runs only when deployment is armed, algo is running (not paused), and market is open.
    """
    global _ato, _ato_warn
    if _deployment is None or not _algo_running or _algo_paused:
        return
    if not _is_sim_market_hours():
        return

    pos = _deployment["positions"]
    ce_sell = pos["ce_sell"]["strike"]
    pe_sell = pos["pe_sell"]["strike"]
    ato_cfg = _deployment.get("ato", {})
    retrace = _deployment.get("retrace_points", 20)
    ce_entry_buffer = int(ato_cfg.get("ce_entry_buffer_points", 0))
    pe_entry_buffer = int(ato_cfg.get("pe_entry_buffer_points", 0))
    ce_trigger = ce_sell + ce_entry_buffer
    pe_trigger = pe_sell - pe_entry_buffer
    sides = _deployment.get("ato_manage_sides", "both")
    spot = _nifty_spot

    # ── CE side ──────────────────────────────────────────────────────────────
    if sides in ("ce", "both"):
        if not _ato["ce"]:
            in_warn = ce_trigger - 50 <= spot < ce_trigger
            if spot >= ce_trigger:
                _ato["ce"] = True
                _ato["ce_cycles"] += 1
                _ato_warn["ce"] = False
                sym = ato_cfg.get("ce_protect_symbol", "?")
                pstrike = ato_cfg.get("ce_protect_strike", "?")
                _record_sim_ato_entry(
                    side="CE",
                    spot=spot,
                    sell_strike=ce_sell,
                    trigger_level=ce_trigger,
                    protect_symbol=str(sym),
                    protect_strike=int(pstrike) if isinstance(pstrike, int) else 0,
                    entry_buffer_points=ce_entry_buffer,
                    retrace_points=int(retrace),
                )
                detail = f"BUY {sym} @ {pstrike:,}" if isinstance(pstrike, int) else f"BUY {sym}"
                _log_algo_event(
                    "trigger", f"CE ATO TRIGGERED  NIFTY {spot:,.0f} >= {ce_trigger:,}", detail
                )
                _bot(
                    "kavach",
                    (
                        f"ATO CE triggered!\n\n"
                        f"NIFTY: {spot:,.0f} >= CE trigger: {ce_trigger:,}\n"
                        f"Placing BUY @ {sym}\n"
                        f"Cycle #{_ato['ce_cycles']}"
                    ),
                )
            elif in_warn and not _ato_warn["ce"]:
                _ato_warn["ce"] = True
                _log_algo_event(
                    "warn",
                    f"CE trigger approaching  {ce_trigger - spot:.0f} pts away",
                    f"CE trigger: {ce_trigger:,} | Spot: {spot:,.0f}",
                )
            elif not in_warn:
                _ato_warn["ce"] = False
        else:  # CE triggered — check retrace
            retrace_level = ce_sell - retrace
            if spot <= retrace_level:
                _ato["ce"] = False
                sym = ato_cfg.get("ce_protect_symbol", "?")
                _record_sim_ato_exit(
                    side="CE",
                    spot=spot,
                    exit_trigger_level=retrace_level,
                    exit_order_tag=f"SIM-CE-EXIT-{_sim_time.strftime('%H%M%S')}",
                )
                _log_algo_event(
                    "exit",
                    f"CE ATO EXITED  NIFTY {spot:,.0f} <= {retrace_level:,}",
                    f"SELL {sym} (retrace {retrace}pts)",
                )
                _bot(
                    "kavach",
                    (
                        f"CE ATO exited (retrace)\n\n"
                        f"NIFTY: {spot:,.0f} <= {retrace_level:,}\n"
                        f"Closing CE protect position."
                    ),
                )

    # ── PE side ──────────────────────────────────────────────────────────────
    if sides in ("pe", "both"):
        if not _ato["pe"]:
            in_warn = pe_trigger < spot <= pe_trigger + 50
            if spot <= pe_trigger:
                _ato["pe"] = True
                _ato["pe_cycles"] += 1
                _ato_warn["pe"] = False
                sym = ato_cfg.get("pe_protect_symbol", "?")
                pstrike = ato_cfg.get("pe_protect_strike", "?")
                _record_sim_ato_entry(
                    side="PE",
                    spot=spot,
                    sell_strike=pe_sell,
                    trigger_level=pe_trigger,
                    protect_symbol=str(sym),
                    protect_strike=int(pstrike) if isinstance(pstrike, int) else 0,
                    entry_buffer_points=pe_entry_buffer,
                    retrace_points=int(retrace),
                )
                detail = f"BUY {sym} @ {pstrike:,}" if isinstance(pstrike, int) else f"BUY {sym}"
                _log_algo_event(
                    "trigger", f"PE ATO TRIGGERED  NIFTY {spot:,.0f} <= {pe_trigger:,}", detail
                )
                _bot(
                    "kavach",
                    (
                        f"ATO PE triggered!\n\n"
                        f"NIFTY: {spot:,.0f} <= PE trigger: {pe_trigger:,}\n"
                        f"Placing BUY @ {sym}\n"
                        f"Cycle #{_ato['pe_cycles']}"
                    ),
                )
            elif in_warn and not _ato_warn["pe"]:
                _ato_warn["pe"] = True
                _log_algo_event(
                    "warn",
                    f"PE trigger approaching  {spot - pe_trigger:.0f} pts away",
                    f"PE trigger: {pe_trigger:,} | Spot: {spot:,.0f}",
                )
            elif not in_warn:
                _ato_warn["pe"] = False
        else:  # PE triggered — check retrace
            retrace_level = pe_sell + retrace
            if spot >= retrace_level:
                _ato["pe"] = False
                sym = ato_cfg.get("pe_protect_symbol", "?")
                _record_sim_ato_exit(
                    side="PE",
                    spot=spot,
                    exit_trigger_level=retrace_level,
                    exit_order_tag=f"SIM-PE-EXIT-{_sim_time.strftime('%H%M%S')}",
                )
                _log_algo_event(
                    "exit",
                    f"PE ATO EXITED  NIFTY {spot:,.0f} >= {retrace_level:,}",
                    f"SELL {sym} (retrace {retrace}pts)",
                )
                _bot(
                    "kavach",
                    (
                        f"PE ATO exited (retrace)\n\n"
                        f"NIFTY: {spot:,.0f} >= {retrace_level:,}\n"
                        f"Closing PE protect position."
                    ),
                )


# ═══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════════════════


@app.route("/")
def index():
    return send_from_directory(str(Path(__file__).parent), "index.html")


@app.route("/api/messages")
def api_messages():
    after = int(request.args.get("after", 0))
    with _lock:
        result = [m for m in _messages if m["id"] > after]
    return jsonify(result)


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.json
    bot, text = data.get("bot"), data.get("text", "").strip()
    if not text:
        return jsonify({"ok": False})
    _user(bot, text)

    def _process():
        time.sleep(0.15)  # feels natural
        if bot == "drishti":
            _handle_drishti(text)
        elif bot == "kavach":
            _handle_kavach(text)
        elif bot == "sanchalak":
            _handle_sanchalak(text)
        elif bot == "saransh":
            _handle_saransh(text)
        elif bot == "jagran":
            _handle_jagran(text)
        # LAKSHMI deferred — uncomment when bot is live:
        # elif bot == "lakshmi":
        #     _handle_lakshmi(text)

    threading.Thread(target=_process, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/keyboard", methods=["POST"])
def api_keyboard():
    data = request.json
    bot, cb = data.get("bot"), data.get("data")
    threading.Thread(target=lambda: _handle_keyboard(bot, cb), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/state")
def api_state():
    tok, _ = _token_store.load()
    sim_age = _sim_token_age_hours()
    return jsonify(
        {
            "token_connected": tok is not None or _sim_token_saved_at is not None,
            "token_age_h": round(_token_store.token_age_hours() or 0, 1),
            "deployment": _deployment is not None,
            "algo_running": _algo_running,
            "algo_paused": _algo_paused,
            "nifty_spot": _nifty_spot,
            "ato_ce": _ato["ce"],
            "ato_pe": _ato["pe"],
            "pnl": _calc_pnl(),
            # DRISHTI sim-time fields
            "sim_time": _sim_time.isoformat(),
            "sim_time_str": _sim_time.strftime("%H:%M"),
            "sim_date_str": _sim_time.strftime("%a %d-%b"),
            "has_sim_token": _sim_token_saved_at is not None,
            "token_age_sim_h": round(sim_age, 1) if sim_age is not None else None,
            "token_expired_sim": _sim_token_expired(),
            "is_weekday_sim": _sim_time.weekday() < 5,
            "is_market_open_sim": _is_sim_market_hours(),
            "runtime_mode": _runtime_mode,
            "global_enabled": _global_enabled,
            "paused_bots": _paused_bots,
        }
    )


# ── Sim control routes ────────────────────────────────────────────────────────


@app.route("/api/sim/setspot", methods=["POST"])
def sim_setspot():
    global _nifty_spot
    _nifty_spot = float(request.json.get("spot", _nifty_spot))
    return jsonify({"spot": _nifty_spot})


@app.route("/api/sim/breach", methods=["POST"])
def sim_breach():
    global _nifty_spot, _ato
    side = request.json.get("side", "CE").upper()
    if not _deployment:
        return jsonify({"error": "No deployment"})
    ato = _deployment["ato"]
    ce_sell_strike = _deployment["positions"]["ce_sell"]["strike"]
    pe_sell_strike = _deployment["positions"]["pe_sell"]["strike"]
    if side == "CE":
        new_spot = ce_sell_strike + 2
        _nifty_spot = new_spot
        _ato["ce"] = True
        _ato["ce_cycles"] += 1

        def _alert():
            _bot(
                "kavach",
                (
                    f"🚨 ATO ALERT — CE SIDE\n\n"
                    f"NIFTY: ₹{new_spot:,.0f}  🔴  (touched CE sell {ce_sell_strike:,}!)\n\n"
                    f"Buying CE protection:\n"
                    f"  {ato['ce_protect_symbol']}  |  qty=1,560  |  MKT order\n\n"
                    f"Reason: NIFTY ({new_spot:,.0f}) ≥ CE sell strike ({ce_sell_strike:,})\n"
                    f"ATO Cycle: {_ato['ce_cycles']} of {_ato['max_cycles']} max."
                ),
            )
            # LAKSHMI push deferred

        threading.Thread(target=_alert, daemon=True).start()
    else:
        new_spot = pe_sell_strike - 2
        _nifty_spot = new_spot
        _ato["pe"] = True
        _ato["pe_cycles"] += 1

        def _alert():
            _bot(
                "kavach",
                (
                    f"🚨 ATO ALERT — PE SIDE\n\n"
                    f"NIFTY: ₹{new_spot:,.0f}  🔴  (touched PE sell {pe_sell_strike:,}!)\n\n"
                    f"Buying PE protection:\n"
                    f"  {ato['pe_protect_symbol']}  |  qty=1,560  |  MKT order\n\n"
                    f"Reason: NIFTY ({new_spot:,.0f}) ≤ PE sell strike ({pe_sell_strike:,})\n"
                    f"ATO Cycle: {_ato['pe_cycles']} of {_ato['max_cycles']} max."
                ),
            )
            # LAKSHMI push deferred

        threading.Thread(target=_alert, daemon=True).start()
    return jsonify({"ok": True, "spot": _nifty_spot})


@app.route("/api/sim/retrace", methods=["POST"])
def sim_retrace():
    global _nifty_spot, _ato
    side = request.json.get("side", "CE").upper()
    if not _deployment:
        return jsonify({"error": "No deployment"})
    ato = _deployment["ato"]
    if side == "CE":
        new_spot = ato["ce_protect_strike"] - 70
        _nifty_spot = new_spot
        _ato["ce"] = False
        _bot(
            "kavach",
            (
                f"✅ ATO RETRACE EXIT — CE side\n\n"
                f"NIFTY pulled back to ₹{new_spot:,.0f}.\n\n"
                f"Selling CE protection:\n"
                f"  {ato['ce_protect_symbol']}  |  qty=1,560  |  MKT order\n\n"
                f"ATO cycle closed. Monitoring continues. 🦇"
            ),
        )
    else:
        new_spot = ato["pe_protect_strike"] + 70
        _nifty_spot = new_spot
        _ato["pe"] = False
        _bot(
            "kavach",
            (
                f"✅ ATO RETRACE EXIT — PE side\n\n"
                f"NIFTY pulled back to ₹{new_spot:,.0f}.\n\n"
                f"Selling PE protection:\n"
                f"  {ato['pe_protect_symbol']}  |  qty=1,560  |  MKT order\n\n"
                f"ATO cycle closed. Monitoring continues. 🦇"
            ),
        )
    return jsonify({"ok": True, "spot": _nifty_spot})


@app.route("/api/sim/reset", methods=["POST"])
def sim_reset():
    global _messages, _next_id, _deployment, _wizard, _algo_running, _algo_paused
    global _ato, _batman_complete_pending, _exit_pending, _nifty_spot
    global _sim_time, _algo_events, _event_id_counter, _ato_warn, _sim_token_saved_at
    global _ato_trade_ledger, _ato_open_entries, _runtime_mode, _global_enabled, _paused_bots
    with _lock:
        _messages.clear()
        _next_id = 1
    _deployment = None
    _wizard = None
    _algo_running = False
    _algo_paused = False
    _ato = {"ce": False, "pe": False, "ce_cycles": 0, "pe_cycles": 0, "max_cycles": 3}
    _batman_complete_pending = False
    _exit_pending = False
    _nifty_spot = 22713.0
    _sim_time = datetime.now().replace(second=0, microsecond=0)
    _algo_events.clear()
    _event_id_counter = 0
    _ato_warn = {"ce": False, "pe": False}
    _ato_trade_ledger.clear()
    _ato_open_entries = {"CE": None, "PE": None}
    _sim_token_saved_at = None
    _runtime_mode = "mock"
    _global_enabled = True
    _paused_bots = {"drishti": False, "kavach": False, "saransh": False, "jagran": False}
    _send_startup()
    return jsonify({"ok": True})


@app.route("/api/sim/trigger_reminder", methods=["POST"])
def sim_trigger_reminder():
    """Manually fire a TYPE 1 DRISHTI token reminder (ignores time/day gate)."""
    threading.Thread(target=_fire_drishti_reminder, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/sim/health_alert", methods=["POST"])
def sim_health_alert():
    """Simulate a TYPE 2 DRISHTI health alert (broker/LTP connectivity failure)."""
    data = request.get_json(silent=True) or {}
    err = data.get("error", "NIFTY LTP fetch timed out after 3 retries")

    def _alert():
        time.sleep(0.3)
        _bot(
            "drishti",
            (
                f"\u274c [Health Alert] {err}\n\n"
                f"Cannot verify broker connection during market hours.\n"
                f"Sim time: {_sim_time.strftime('%H:%M IST \u00b7 %a %d-%b')}\n\n"
                f"Action: run /update_token to refresh the Dhan JWT,\n"
                f"or check server connectivity."
            ),
        )
        _log_algo_event("warn", f"TYPE 2 health alert: {err}", _sim_time.strftime("%H:%M"))

    threading.Thread(target=_alert, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/sim/process_restart", methods=["POST"])
def sim_process_restart():
    """Simulate a VPS process restart.

    1. Save current _deployment as the 'file on disk'.
    2. Wipe in-memory state (algo stopped, ATO reset) — simulates process death.
    3. Re-read the 'file' and validate positions against mock broker.
    4. Send appropriate KAVACH notification.
    """
    global _messages, _next_id, _deployment, _wizard, _algo_running, _algo_paused
    global _ato, _batman_complete_pending, _exit_pending, _global_enabled

    snapshot = _deployment  # treat current in-memory deployment as the saved file

    # ── Wipe memory (simulate process death) ──────────────────────────────
    with _lock:
        _messages.clear()
        _next_id = 1
    _wizard = None
    _algo_running = False
    _algo_paused = False
    _ato = {"ce": False, "pe": False, "ce_cycles": 0, "pe_cycles": 0, "max_cycles": 3}
    _batman_complete_pending = False
    _exit_pending = False
    _global_enabled = True

    # ── Post-restart startup message ──────────────────────────────────────
    _bot(
        "drishti",
        ("⚡ Batman v3 restarted (VPS reboot)\n\n" "Checking for previous deployment file…"),
    )

    if snapshot is None:
        # No file to restore from
        _deployment = None
        _bot(
            "kavach",
            (
                "♻️ No previous deployment file found.\n\n"
                "KAVACH is fresh. Run /register to deploy positions."
            ),
        )
        return jsonify({"ok": True, "restored": False})

    # ── Restore from file ─────────────────────────────────────────────────
    _deployment = snapshot  # re-load from 'disk'
    _algo_running = True  # monitoring resumes

    pos = snapshot.get("positions", {})
    ato = snapshot.get("ato", {})
    retrace_pts = snapshot.get("retrace_points", 0)
    registered_at = snapshot.get("registered_at", "(unknown)")
    file_name = snapshot.get("file_name", "batman_?.json")

    # In simulation: broker always has all 4 positions (Option B: flip a flag to test mismatch)
    # Build position lines
    role_label = {
        "pe_buy": "PE BUY ",
        "pe_sell": "PE SELL",
        "ce_buy": "CE BUY ",
        "ce_sell": "CE SELL",
    }
    role_order = ["pe_buy", "pe_sell", "ce_buy", "ce_sell"]
    pos_lines = ""
    for role in role_order:
        if role not in pos:
            continue
        leg = pos[role]
        label = role_label.get(role, role)
        pos_lines += f"  ✅ {label} : {leg['symbol']}  qty={leg['qty']}\n"

    ce_strike = ato.get("ce_sell_strike") or pos.get("ce_sell", {}).get("strike", "?")
    pe_strike = ato.get("pe_sell_strike") or pos.get("pe_sell", {}).get("strike", "?")
    ce_entry_buffer = int(ato.get("ce_entry_buffer_points", 0))
    pe_entry_buffer = int(ato.get("pe_entry_buffer_points", 0))
    ce_trigger = ce_strike + ce_entry_buffer if isinstance(ce_strike, int) else ce_strike
    pe_trigger = pe_strike - pe_entry_buffer if isinstance(pe_strike, int) else pe_strike
    ce_ato = ato.get("ce_protect_strike", "?")
    pe_ato = ato.get("pe_protect_strike", "?")

    _bot(
        "kavach",
        (
            f"♻️ Previous deployment found & VALIDATED\n"
            f"Registered: {registered_at}\n"
            f"File: {file_name}\n\n"
            f"📋 Deployed positions (all CONFIRMED at broker):\n"
            f"{pos_lines}\n"
            f"🛡 ATO config restored:\n"
            f"  CE fires when NIFTY ≥ {ce_trigger:,} (ATO at {ce_ato:,}, buffer +{ce_entry_buffer})\n"
            f"  PE fires when NIFTY ≤ {pe_trigger:,} (ATO at {pe_ato:,}, buffer -{pe_entry_buffer})\n"
            f"  Retrace: {retrace_pts} pts\n\n"
            f"✅ ATO monitoring resumed automatically.\n"
            f"KAVACH is watching. 🦇"
        ),
        mono=True,
    )

    return jsonify({"ok": True, "restored": True})


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET SIMULATOR ROUTES  — /market  +  /api/market/*
# ═══════════════════════════════════════════════════════════════════════════════


@app.route("/market")
def market_page():
    resp = send_from_directory(str(Path(__file__).parent), "market.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/market/state")
def market_state_api():
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    pos_out: dict = {}
    if _deployment:
        p = _deployment["positions"]
        ato = _deployment.get("ato", {})
        pos_out = {
            "pe_buy": p.get("pe_buy", {}).get("strike"),
            "pe_sell": p.get("pe_sell", {}).get("strike"),
            "ce_sell": p.get("ce_sell", {}).get("strike"),
            "ce_buy": p.get("ce_buy", {}).get("strike"),
            "pe_ato": ato.get("pe_protect_strike"),
            "ce_ato": ato.get("ce_protect_strike"),
            "pe_entry_buffer": ato.get("pe_entry_buffer_points", 0),
            "ce_entry_buffer": ato.get("ce_entry_buffer_points", 0),
            "retrace": _deployment.get("retrace_points", 20),
        }
    expiry_wd = (_deployment or {}).get("expiry_weekday", 1)
    ato_ledger = _sim_ato_ledger_snapshot()
    return jsonify(
        {
            "sim_time": _sim_time.isoformat(),
            "sim_date_str": _sim_time.strftime("%a %d-%b-%Y"),
            "sim_time_str": _sim_time.strftime("%H:%M"),
            "weekday": weekday_names[_sim_time.weekday()],
            "is_market_open": _is_sim_market_hours(),
            "is_expiry_day": _sim_time.weekday() == expiry_wd,
            "is_entry_day": _sim_time.weekday() == 2,  # Wednesday
            "nifty_spot": _nifty_spot,
            "deployment_armed": _deployment is not None,
            "algo_running": _algo_running,
            "algo_paused": _algo_paused,
            "ato_ce": _ato["ce"],
            "ato_pe": _ato["pe"],
            "ato_ce_cycles": _ato["ce_cycles"],
            "ato_pe_cycles": _ato["pe_cycles"],
            "strikes": pos_out,
            "ato_ledger": ato_ledger,
            "last_event_id": _algo_events[-1]["id"] if _algo_events else 0,
        }
    )


@app.route("/api/market/advance", methods=["POST"])
def market_advance():
    """Advance simulated time by N minutes (default 5)."""
    global _sim_time
    data = request.get_json(silent=True) or {}
    minutes = int(data.get("minutes", 5))
    old_time = _sim_time
    old_open = _is_sim_market_hours()
    _sim_time += timedelta(minutes=minutes)
    new_open = _is_sim_market_hours()
    if not old_open and new_open:
        _log_algo_event("time", "Market OPENED", f"09:15 IST  {_sim_time.strftime('%a %d-%b')}")
    elif old_open and not new_open:
        _log_algo_event("time", "Market CLOSED", f"15:30 IST  {_sim_time.strftime('%a %d-%b')}")
    else:
        _log_algo_event("info", f"Time +{minutes}m  →  {_sim_time.strftime('%a %d-%b %H:%M')}", "")
    _new_time = _sim_time
    threading.Thread(
        target=lambda: _check_drishti_reminders(old_time, _new_time), daemon=True
    ).start()
    return jsonify({"ok": True, "sim_time": _sim_time.isoformat()})


@app.route("/api/market/settime", methods=["POST"])
def market_set_time():
    global _sim_time
    data = request.get_json(silent=True) or {}
    ts = data.get("datetime")
    if not ts:
        return jsonify({"ok": False, "error": "missing datetime"}), 400
    try:
        old_time = _sim_time
        _sim_time = datetime.fromisoformat(ts).replace(second=0, microsecond=0)
        _log_algo_event("time", "Time set manually", _sim_time.strftime("%a %d-%b-%Y %H:%M"))
        _new_time = _sim_time
        threading.Thread(
            target=lambda: _check_drishti_reminders(old_time, _new_time), daemon=True
        ).start()
        return jsonify({"ok": True, "sim_time": _sim_time.isoformat()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/market/setnifty", methods=["POST"])
def market_set_nifty():
    global _nifty_spot
    data = request.get_json(silent=True) or {}
    spot = data.get("spot")
    if spot is None:
        return jsonify({"ok": False, "error": "missing spot"}), 400
    _nifty_spot = float(spot)
    _auto_check_ato()
    return jsonify({"ok": True, "spot": _nifty_spot})


@app.route("/api/market/events")
def market_events_api():
    after_id = int(request.args.get("after", 0))
    events = [e for e in _algo_events if e["id"] > after_id]
    return jsonify({"events": events})


@app.route("/api/market/preset", methods=["POST"])
def market_preset():
    """Apply a named scenario preset (time or price)."""
    global _sim_time, _nifty_spot
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    old_time = _sim_time

    base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    def _next_wd(wd: int) -> datetime:
        days = wd - base.weekday()
        if days <= 0:
            days += 7
        return base + timedelta(days=days)

    if name == "wed_entry":
        _sim_time = _next_wd(2).replace(hour=11, minute=0)
        _log_algo_event("time", "Preset: Wednesday 11:00 — Entry window", "ATO monitoring active")
    elif name == "tue_open":
        _sim_time = _next_wd(1).replace(hour=9, minute=20)
        _log_algo_event("time", "Preset: Tuesday 09:20 — Expiry day open", "Gap-up/gap-down risk")
    elif name == "tue_afternoon":
        _sim_time = _next_wd(1).replace(hour=14, minute=30)
        _log_algo_event("time", "Preset: Tuesday 14:30 — Expiry PM", "Profit trailing scenario")
    elif name == "pre_market":
        _sim_time = _next_wd(3).replace(hour=9, minute=0)
        _log_algo_event("time", "Preset: Thursday 09:00 — Pre-market", "ATO sleeping")
    elif name == "after_close":
        _sim_time = _next_wd(3).replace(hour=15, minute=45)
        _log_algo_event("time", "Preset: Thursday 15:45 — After close", "Market closed")
    elif name == "weekend":
        sat = base + timedelta(days=(5 - base.weekday()) % 7 or 7)
        _sim_time = sat.replace(hour=12, minute=0)
        _log_algo_event("time", "Preset: Saturday noon — Weekend", "Market closed")
    elif name == "center":
        if _deployment:
            pe_sell = _deployment["positions"]["pe_sell"]["strike"]
            ce_sell = _deployment["positions"]["ce_sell"]["strike"]
            _nifty_spot = round((pe_sell + ce_sell) / 2 / 5) * 5
            _log_algo_event(
                "info", f"Price: Center of range  {_nifty_spot:,.0f}", "Max profit zone"
            )
    elif name == "ce_approach":
        if _deployment:
            ce_s = _deployment["positions"]["ce_sell"]["strike"]
            _nifty_spot = float(ce_s - 30)
            _auto_check_ato()
            _log_algo_event(
                "info", f"Price: CE sell -30pts  {_nifty_spot:,.0f}", f"CE sell: {ce_s:,}"
            )
    elif name == "pe_approach":
        if _deployment:
            pe_s = _deployment["positions"]["pe_sell"]["strike"]
            _nifty_spot = float(pe_s + 30)
            _auto_check_ato()
            _log_algo_event(
                "info", f"Price: PE sell +30pts  {_nifty_spot:,.0f}", f"PE sell: {pe_s:,}"
            )
    # Fire DRISHTI reminder check if sim-time changed
    if _sim_time != old_time:
        _new_time = _sim_time
        threading.Thread(
            target=lambda: _check_drishti_reminders(old_time, _new_time), daemon=True
        ).start()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════


def _send_startup() -> None:
    global _sim_token_saved_at
    tok, _ = _token_store.load()
    if tok:
        # Treat disk token as freshly loaded at current sim-time (age = 0 from sim perspective)
        if _sim_token_saved_at is None:
            _sim_token_saved_at = _sim_time
        age_h = _token_store.token_age_hours() or 0
        sim_expiry = (_sim_token_saved_at + timedelta(hours=24)).strftime("%H:%M IST")
        _bot(
            "drishti",
            (
                f"⚡ Batman v3 is ONLINE\n\n"
                f"Token auto-loaded from disk (real age: {age_h:.1f}h).\n"
                f"Sim clock: {_sim_time.strftime('%H:%M IST')}  —  advance time to test expiry\n"
                f"Sim expiry: {sim_expiry}\n"
                f"Broker connected automatically.\n\n"
                f"🦇 Batman is ready.\n"
                f"Open KAVACH and run /register to register positions."
            ),
        )
        _bot("sanchalak", "🎛 SANCHALAK online. Use /status_all for global controls.")
        _bot("saransh", "📘 SARANSH online. Use /summary for current report.")
        _bot("jagran", "🚨 JAGRAN online. Use /status or /recent.")
    else:
        _sim_token_saved_at = None
        _bot(
            "drishti",
            (
                "⚡ Batman v3 is ONLINE\n\n"
                "VPS started successfully.\n\n"
                "🔴 Broker not connected.\n"
                "No saved access token found.\n\n"
                "Paste your Dhan access token here and I will connect immediately.\n"
                "Token is valid for 24 hours.\n\n"
                "Tip: Get your token from Dhan Developer Portal → Access Token."
            ),
        )
        _bot("sanchalak", "🎛 SANCHALAK online. Use /status_all for global controls.")
        _bot("saransh", "📘 SARANSH online. Use /summary for current report.")
        _bot("jagran", "🚨 JAGRAN online. Use /status or /recent.")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _send_startup()
    print("\n" + "=" * 55)
    print("  Batman v3 Simulator")
    print("  Open: http://localhost:5001")
    print("  Stop: Ctrl+C")
    print("=" * 55 + "\n")
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
