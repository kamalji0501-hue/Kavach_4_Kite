"""
Batman v3 — KAVACH Bot (कवच)

Bot 2 of 3.  Runs as an asyncio task inside ``main.py``.

Responsibilities (LOCKED 2026-04-04):
    • /register — 4-leg deploy wizard + ATO auto-calc + arm Batman
    • /batman_complete — full cleanup: stop modules, archive file, reset state
    • /ato_status — ATO state per side (triggered/idle, cycles)
    • /ato_tune — ATO Configuration (Quick Tune entry/exit buffers)
    • /pause — pause ATO monitoring loop
    • /resume — resume ATO monitoring loop
    • /start_algo_now — force-start algo immediately
    • /legs — show current open Batman legs from deployment file
    • /funds — available margin from broker
    • /status — system & module status
    • Proactive ATO notifications (CE/PE triggered, exited, max cycles)

Does NOT own: /pnl, token management, broker health.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import zoneinfo
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from bat_telegram.bots.kavach2.register_wizard import (
    WIZARD_CONFIRM,
    WIZARD_ORDER_MODE,
    WIZARD_PE_INTENT,
    build_wizard_handler,
    pe_intent_keyboard,
)
from bat_telegram.control import guard_paused_command
from bat_telegram.incident_publisher import publish_incident
from bat_telegram.loader import load_bot_config
from core.batman_cleanup import (
    format_cleanup_verification_message,
    open_ato_protect_lines,
    run_cleanup_with_retries,
    verify_batman_cleanup,
)
from core.buffer_config import (
    buffer_display,
    legacy_int_from_buffer,
    normalize_buffer_field,
    serialize_buffer_field,
)
from core.buffer_config.schema import BufferKind
from core.deployment_lock import DeploymentLockBusy, deployment_session
from core.position_scope import (
    auto_protect_strike,
    broker_buy_lots,
    build_registration_scope,
    legacy_registration_scope_from_deployment,
    protect_strike_direction_warnings,
)
from core.positions import (
    build_ato_protect_symbol,
)
from core.positions import (
    filter_nifty_positions as _filter_nifty_positions,
)
from core.telegram_runtime import cleanup_managed_runtime
from core.utils import current_week_expiry, is_trading_day
from core.wizard_plan import question_index, rebuild_wizard_plan, register_intro_text
from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)

logger = logging.getLogger("batman.kavach2")

# ── Deployment paths (mode-aware runtime under Trading_Runtime/Data) ───────────
from core.batman_mode import data_root as _batman_data_root  # noqa: E402

_DEPLOY_DIR = _batman_data_root() / "deployments"
_ARCHIVE_DIR = _DEPLOY_DIR / "archive"
_DEPLOY_LOG = _DEPLOY_DIR / "deploy_log.jsonl"
_AUDIT_ROOT = Path.home() / "Desktop" / "batman execution"

# ── Wizard conversation states (legacy BE/buffer constants kept for future release) ──
from bat_telegram.bots.kavach2.register_wizard import (  # noqa: E402
    WIZARD_CONVERSATION_NAME,
    WIZARD_POLL_INTERVAL,
)

WIZARD_STEP1 = WIZARD_STEP2 = WIZARD_STEP3 = WIZARD_STEP4 = 0  # legacy refs
WIZARD_BE_PE = WIZARD_BE_PE_MANUAL = WIZARD_BE_CE = WIZARD_BE_CE_MANUAL = 0
WIZARD_BE_SKIP_CONFIRM = WIZARD_CE_BUFFER = WIZARD_PE_BUFFER = 0
WIZARD_CE_RETRACE = WIZARD_PE_RETRACE = WIZARD_STEP6 = WIZARD_STEP7 = 0

# ── Callback data prefixes ────────────────────────────────────────────────────
_CB_PRE = "wiz_pre"  # pre-confirm safety check
_CB_LEG = "wiz_leg"  # leg selection buttons
_CB_RETRACE = "wiz_ret"  # retrace_points picker (Step 5/6)
_CB_ATO_MON = "wiz_ato_mon"  # ATO monitor side picker (Step 6/6)
_CB_HOL = "wiz_hol"  # holiday selection review (Step 7/7)
_CB_CONF = "wiz_conf"  # final confirm/cancel
_CB_DONE = "kav2_done"  # batman_complete confirm
_CB_DYN_HEDGE = "kav2_dynhedge"  # 30% dynamic hedge Yes/No
_CB_BE = "wiz_be"  # break-even confirm/edit/skip
_CB_BUF = "wiz_buf"  # side-wise ATO trigger buffers
_CB_POLL = "wiz_poll"  # per-deployment poll interval
_CB_HB = "hb"  # Hedge Box confirm / deny
_CB_MENU = "kav2_menu"  # main alive menu buttons

# ── Phase 1 wizard feature gates (re-enable in future releases) ───────────────
# Break-even capture — legacy Register wizard (deferred). RATRIPAL now uses
# fixed sell±200 BE; ADITYA is the morning hedge-exit module (formerly PRABHAT MUKTI).
# Set True to restore PE/CE break-even prompts + skip-confirm in /register.
_WIZARD_BREAK_EVEN_ENABLED = False

# Trading-days / holiday review — feeds Hedge Box calendar (deferred phase).
# Set True to restore Step 7/7 holiday toggle before confirm summary.
_WIZARD_TRADING_DAYS_REVIEW_ENABLED = False

# Active wizard length (leg pick → ATO sides, before confirm).
_WIZARD_STEPS_TOTAL = 10

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")

_READ_ONLY_COMMANDS = {
    "start",
    "help",
    "status",
    "funds",
    "corelegs",
    "positions",
    "ato_status",
    "ato_tune",
    "ato",
    "ping",
}


def _read_algo_pause_reason() -> str | None:
    from core.batman_mode import state_path, workspace_root
    from core.state import StateManager

    try:
        sm = StateManager(path=state_path(workspace_root()))
        raw = sm.get("algo.pause_reason")
        return str(raw) if raw else None
    except Exception:
        return None




def _btn(text: str, callback_data: str, *, style: str | None = None) -> InlineKeyboardButton:
    """Inline button with optional Telegram style: primary|success|danger (same as GO)."""
    kwargs: dict[str, Any] = {"text": text, "callback_data": callback_data}
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    """KAVACH 2.0 home menu.

    Layout:
      Deploy Batman 2.0
      Kavach Status | ATO Status
      ATO           | Buffer Manager
      Core Legs     | Environment
      Pause         | Resume
      30% Dynamic Hedge
      Register Batman
      Complete Batman

    Styles match GO (success=green, primary=blue, danger=red).
    """
    return InlineKeyboardMarkup(
        [
            [
                _btn(
                    "🦇 Deploy Batman 2.0",
                    f"{_CB_MENU}:deploy_batman2",
                    style="success",
                ),
            ],
            [
                _btn("🛡️ Kavach Status", f"{_CB_MENU}:status", style="primary"),
                _btn("🎯 ATO Status", f"{_CB_MENU}:ato_status", style="primary"),
            ],
            [
                _btn("📊 ATO", f"{_CB_MENU}:positions", style="primary"),
                _btn("🎚️ Buffer Manager", f"{_CB_MENU}:ato_tune", style="primary"),
            ],
            [
                _btn("🧩 Core Legs", f"{_CB_MENU}:corelegs", style="primary"),
                _btn("🌐 Environment", f"{_CB_MENU}:environment", style="primary"),
            ],
            [
                _btn("⏸️ Pause", f"{_CB_MENU}:pause", style="danger"),
                _btn("▶️ Resume", f"{_CB_MENU}:resume", style="success"),
            ],
            [
                _btn(
                    "🛡 30% Dynamic Hedge",
                    f"{_CB_MENU}:dyn_hedge",
                    style="primary",
                ),
            ],
            [
                _btn(
                    "🦇 Register Batman",
                    f"{_CB_MENU}:register",
                    style="success",
                ),
            ],
            [
                _btn(
                    "✅ Complete Batman",
                    f"{_CB_MENU}:batman_complete",
                    style="success",
                ),
            ],
        ]
    )


async def _send_alive_menu(message: Message) -> None:
    """KAVACH alive card: clear logo on top, then status content + menu buttons."""
    from bat_telegram.alive_branding import reply_alive_card
    from core.environment_display import environment_label

    now = datetime.now(_IST).strftime("%d-%b-%Y %H:%M:%S IST")
    dep_file = _find_active_deployment()
    if dep_file:
        armed = f"Armed ({dep_file.name})"
    else:
        armed = "Not deployed"
    mode_label = environment_label().replace("(virtual)", "(Virtual)").replace("(live)", "(Live)")
    caption = (
        f"🟢 <b>KAVACH 2.0 ACTIVE</b>\n"
        f"Mode: <b>{mode_label}</b>\n"
        f"<code>{now}</code>\n"
        f"Deployment: <b>{armed}</b>"
    )
    await reply_alive_card(
        message,
        caption,
        reply_markup=_main_menu_keyboard(),
        bot_name="kavach2",
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


def _wizard_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return cast(dict[str, Any], context.user_data)


# ═══════════════════════════════════════════════════════════════════════════════
# Deployment file helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _append_log(event: str, **kwargs: Any) -> None:
    """Append one event to persistent audit logs (project + desktop daily mirror)."""
    _DEPLOY_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now().astimezone().isoformat(), "event": event, **kwargs}
    with open(_DEPLOY_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

    # User-facing execution audit mirror:
    # Desktop/batman execution/YYYY-MM/YYYY-MM-DD/kavach_audit.jsonl
    try:
        audit_log = _daily_audit_dir() / "kavach2_audit.jsonl"
        with open(audit_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.warning("KAVACH audit mirror write failed: %s", exc)


def _daily_audit_dir(now: datetime | None = None) -> Path:
    """Return Desktop execution audit dir for current day and ensure it exists."""
    ts = now.astimezone() if now else datetime.now().astimezone()
    month_dir = _AUDIT_ROOT / ts.strftime("%Y-%m")
    day_dir = month_dir / ts.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def _mirror_deployment_to_daily_audit(filepath: Path) -> None:
    """Copy deployment snapshot to Desktop daily audit folder (best effort)."""
    try:
        dest_dir = _daily_audit_dir() / "deployments"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(filepath, dest_dir / filepath.name)
    except Exception as exc:
        logger.warning("KAVACH deployment audit mirror failed for %s: %s", filepath, exc)


def _find_active_deployment() -> Path | None:
    """Return the latest active batman_*.json path, or None."""
    files = sorted(_DEPLOY_DIR.glob("batman_*.json"))
    return files[-1] if files else None


def apply_ato_buffer_patch(
    patches: dict[str, Any],
    *,
    state: Any = None,
) -> Path:
    """Patch entry/exit buffers on the active deployment + live state (Quick Tune).

    Updates typed + legacy buffer fields in-place. Does **not** clear triggered /
    holding flags (unlike full deployment sync) — Q85/Q89.
    """
    from bat_telegram.bots.kavach2.ato_configuration_wizard import apply_patches_dict

    path = _find_active_deployment()
    if path is None:
        raise FileNotFoundError("No active deployment to patch")

    with deployment_session("ato_tune"):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        ato = data.setdefault("ato", {})
        apply_patches_dict(ato, data, patches)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        tmp.replace(path)
        _mirror_deployment_to_daily_audit(path)

    if state is not None:
        state_map = {
            "ce_entry": "ato.ce_entry_buffer_points",
            "pe_entry": "ato.pe_entry_buffer_points",
            "ce_exit": "ato.ce_retrace_points",
            "pe_exit": "ato.pe_retrace_points",
        }
        for target, raw in patches.items():
            key = state_map.get(target)
            if key:
                state.set(key, normalize_buffer_field(raw), save=False)
            if target == "ce_exit":
                state.set(
                    "ato.retrace_points",
                    legacy_int_from_buffer(raw, default=5),
                    save=False,
                )
        try:
            state.save()
        except Exception:
            pass
    _append_log(
        "ato_buffer_patch",
        file=path.name,
        targets=list(patches.keys()),
    )
    return path


def _archive_active_deployments() -> list[str]:
    """Move all batman_*.json from active dir to archive. Returns moved filenames."""
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for f in sorted(_DEPLOY_DIR.glob("batman_*.json")):
        dest = _ARCHIVE_DIR / f.name
        shutil.move(str(f), dest)
        moved.append(f.name)
    return moved


def _construct_symbol(underlying: str, expiry: str, strike: int, opt_type: str) -> str:
    """Build a Dhan option symbol — e.g. NIFTY25APR24800CE."""
    return f"{underlying}{expiry}{strike}{opt_type}"


def _format_position_price(pos: dict[str, Any]) -> str:
    import math

    px = pos.get("avg_price", 0)
    try:
        if px and not math.isnan(float(px)):
            return f"₹{float(px):.2f}"
    except (TypeError, ValueError):
        pass
    return "₹—"


def _parse_protect_symbol_parts(symbol: str) -> tuple[int | None, str | None]:
    """Best-effort strike + CE/PE from an ATO protect trading symbol."""
    text = str(symbol or "").strip().upper()
    if not text:
        return None, None
    # Compact Dhan: NIFTY28JUL2623500CE
    m = re.search(r"(\d{4,6})(CE|PE)$", text)
    if m:
        return int(m.group(1)), m.group(2)
    # UAT / dashed: NIFTY-Jul2026-23500-CE
    m = re.search(r"-(\d{4,6})-(CE|PE)$", text)
    if m:
        return int(m.group(1)), m.group(2)
    return None, None


def _collect_ato_protect_symbols(
    state: Any,
    dep_file: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Map protect tradingSymbol → {side, strike, triggered} from state + deployment."""
    out: dict[str, dict[str, Any]] = {}

    def _add(side: str, symbol: Any, strike: Any = None, triggered: bool = False) -> None:
        sym = str(symbol or "").strip()
        if not sym or sym in {"N/A", "None", "none"}:
            return
        parsed_strike, parsed_opt = _parse_protect_symbol_parts(sym)
        try:
            strike_i = int(strike) if strike not in (None, "", "None") else parsed_strike
        except (TypeError, ValueError):
            strike_i = parsed_strike
        out[sym] = {
            "side": side,
            "strike": strike_i,
            "opt_type": parsed_opt or side,
            "triggered": bool(triggered),
        }

    if state is not None:
        _add(
            "CE",
            state.get("ato.ce_protect_symbol"),
            state.get("ato.ce_protect_strike"),
            bool(state.get("ato.ce_triggered", False)),
        )
        _add(
            "PE",
            state.get("ato.pe_protect_symbol"),
            state.get("ato.pe_protect_strike"),
            bool(state.get("ato.pe_triggered", False)),
        )

    path = dep_file if dep_file is not None else _find_active_deployment()
    if path is not None and path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                dep = json.load(fh)
            ato = dep.get("ato") if isinstance(dep, dict) else {}
            if isinstance(ato, dict):
                # Fill missing sides from deployment without overwriting live state.
                if not any(v["side"] == "CE" for v in out.values()):
                    _add(
                        "CE",
                        ato.get("ce_protect_symbol"),
                        ato.get("ce_protect_strike"),
                        bool(state.get("ato.ce_triggered", False)) if state else False,
                    )
                if not any(v["side"] == "PE" for v in out.values()):
                    _add(
                        "PE",
                        ato.get("pe_protect_symbol"),
                        ato.get("pe_protect_strike"),
                        bool(state.get("ato.pe_triggered", False)) if state else False,
                    )
        except Exception as exc:
            logger.warning("ATO protect symbol load failed: %s", exc)
    return out


def _position_matches_ato_protect(
    pos: dict[str, Any],
    protect: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return protect meta if this broker row is an ATO protect leg."""
    raw = str(pos.get("symbol") or "").strip()
    display = str(pos.get("display_symbol") or "").strip()
    if raw in protect:
        return protect[raw]
    if display in protect:
        return protect[display]
    try:
        pos_strike = int(pos.get("strike")) if pos.get("strike") not in (None, "") else None
    except (TypeError, ValueError):
        pos_strike = None
    pos_opt = str(pos.get("opt_type") or "").upper() or None
    if pos_strike is None or not pos_opt:
        ps, po = _parse_protect_symbol_parts(raw) if raw else (None, None)
        if pos_strike is None:
            pos_strike = ps
        if not pos_opt:
            pos_opt = po
    for meta in protect.values():
        if (
            meta.get("strike") is not None
            and pos_strike is not None
            and int(meta["strike"]) == int(pos_strike)
            and str(meta.get("opt_type") or "").upper() == str(pos_opt or "").upper()
        ):
            return meta
    return None


def _filter_ato_protect_positions(
    positions: list[dict[str, Any]],
    protect: dict[str, dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Keep only open broker rows that match registered ATO protect symbols."""
    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for pos in positions:
        meta = _position_matches_ato_protect(pos, protect)
        if meta is not None:
            matched.append((pos, meta))
    return matched


def _enrich_positions_list(
    context: ContextTypes.DEFAULT_TYPE,
    positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shared prod + UAT: broker avg first, fixture/live LTP only when avg missing."""
    from core.batman_mode import is_uat, workspace_root
    from core.uat_position_enrich import enrich_nifty_positions, resolve_market_quote_broker

    fixture = None
    if is_uat():
        try:
            from core.uat_positions import load_positions_fixture

            fixture = load_positions_fixture(workspace_root())
        except Exception:
            pass
    from core.market_data_guard import should_skip_live_quotes

    skip_live, _ = should_skip_live_quotes(positions, fixture=fixture)
    chain_broker = None
    if not skip_live:
        chain_broker = resolve_market_quote_broker(context.bot_data.get("broker"))
    return enrich_nifty_positions(positions, fixture=fixture, chain_broker=chain_broker)


# Back-compat for tests and patches
_uat_enrich_positions_list = _enrich_positions_list


def _positions_keyboard(available: list[dict]) -> InlineKeyboardMarkup:
    """Build an InlineKeyboardMarkup from the given available positions."""
    buttons = []
    for i, pos in enumerate(available):
        sym = pos.get("display_symbol") or pos["symbol"]
        label = f"{sym} | {pos['direction']} {pos['qty']} | avg {_format_position_price(pos)}"
        buttons.append([_btn(label, f"{_CB_LEG}:{i}", style="primary")])
    buttons.append([_btn("❌ Cancel", f"{_CB_LEG}:cancel", style="danger")])
    return InlineKeyboardMarkup(buttons)


def _retrace_keyboard() -> InlineKeyboardMarkup:
    """Legacy exit-level picker — unused by Buffer Manager / register NIFTY-level flow."""
    options = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
    mid = len(options) // 2
    row1 = [
        _btn(str(v), f"{_CB_RETRACE}:{v}", style="primary") for v in options[:mid]
    ]
    row2 = [
        _btn(str(v), f"{_CB_RETRACE}:{v}", style="primary") for v in options[mid:]
    ]
    cancel = [_btn("❌ Cancel", f"{_CB_RETRACE}:cancel", style="danger")]
    return InlineKeyboardMarkup([row1, row2, cancel])


def _buffer_keyboard(same_value: int | None = None) -> InlineKeyboardMarkup:
    """Legacy entry picker — unused by Buffer Manager / register NIFTY-level flow."""
    options = [0, 5, 10, 15, 20]
    row = [_btn(str(v), f"{_CB_BUF}:{v}", style="primary") for v in options]
    rows = [row]
    if same_value is not None:
        rows.append(
            [
                _btn(
                    f"Use same as CE ({same_value})",
                    f"{_CB_BUF}:same",
                    style="success",
                )
            ]
        )
    rows.append([_btn("❌ Cancel", f"{_CB_BUF}:cancel", style="danger")])
    return InlineKeyboardMarkup(rows)


def _poll_interval_keyboard() -> InlineKeyboardMarkup:
    """Selection-only polling interval keyboard (locked values only)."""
    options = [1, 2, 3, 4, 5, 10, 15]
    row1 = [_btn(f"{v}s", f"{_CB_POLL}:{v}", style="primary") for v in options[:5]]
    row2 = [_btn(f"{v}s", f"{_CB_POLL}:{v}", style="primary") for v in options[5:]]
    cancel = [_btn("❌ Cancel", f"{_CB_POLL}:cancel", style="danger")]
    return InlineKeyboardMarkup([row1, row2, cancel])


def _break_even_keyboard(side: str, manual_only: bool = False) -> InlineKeyboardMarkup:
    side_token = side.lower()
    rows: list[list[InlineKeyboardButton]] = []
    if not manual_only:
        rows.append(
            [
                _btn("✅ Confirm suggestion", f"{_CB_BE}:{side_token}:confirm", style="success")
            ]
        )
    rows.append(
        [_btn("✏️ Edit manually", f"{_CB_BE}:{side_token}:edit", style="primary")]
    )
    rows.append(
        [_btn("⏭ Skip Break-even", f"{_CB_BE}:{side_token}:skip", style="primary")]
    )
    rows.append([_btn("❌ Cancel", f"{_CB_BE}:{side_token}:cancel", style="danger")])
    return InlineKeyboardMarkup(rows)


def _break_even_skip_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                _btn("✅ Skip break-even", f"{_CB_BE}:skip_confirm", style="danger"),
                _btn("↩ Go back", f"{_CB_BE}:skip_back", style="primary"),
            ]
        ]
    )


def _hedge_box_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                _btn("✅ Confirm", f"{_CB_HB}:confirm:{request_id}", style="success"),
                _btn("❌ Deny", f"{_CB_HB}:deny:{request_id}", style="danger"),
            ]
        ]
    )


def _round_to_nearest_50_tie_down(value: float) -> int:
    truncated = int(value)
    remainder = truncated % 50
    lower = truncated - remainder
    return lower if remainder <= 25 else lower + 50


def _wizard_seed_trading_calendar_defaults(wizard_data: dict[str, Any]) -> None:
    """Auto-fill trading calendar when holiday review step is disabled."""
    deploy_date = datetime.now().astimezone().date()
    window = _compute_trade_window(deploy_date)
    wizard_data["wiz_deploy_date"] = window["deploy_date"]
    wizard_data["wiz_expiry_date"] = window["expiry_date"]
    wizard_data["wiz_auto_working_days"] = window["auto_working_days"]
    wizard_data["wiz_extra_holidays"] = []


async def _wizard_goto_ce_buffer(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    selected: dict[str, dict[str, Any]],
) -> int:
    """Skip break-even and continue to CE ATO trigger buffer (Phase 1 default)."""
    wizard_data = _wizard_data(context)
    wizard_data["wiz_break_even"] = {}
    wizard_data["wiz_break_even_source"] = {}
    wizard_data["wiz_break_even_skipped"] = True
    header = _selected_header(selected)
    await _wizard_edit_step(
        context,
        query,
        f"{header}\n\n"
        rf"*Step 5/{_WIZARD_STEPS_TOTAL} — CE ATO Trigger Buffer*\n\n"
        r"Enter the CE fire NIFTY level\.\n"
        r"Enter a NIFTY level \(e\.g\. 24160\)\.",
        reply_markup=_buffer_keyboard(),
    )
    return WIZARD_CE_BUFFER


# ── FUTURE RELEASE: break-even wizard helpers (disabled when flag is False) ───
def _calculate_break_even_suggestions(selected: dict[str, dict[str, Any]]) -> dict[str, int] | None:
    legs = [
        selected.get("pe_buy"),
        selected.get("pe_sell"),
        selected.get("ce_buy"),
        selected.get("ce_sell"),
    ]
    if any(not leg or float(leg.get("avg_price") or 0) <= 0 for leg in legs):
        return None

    total_credit = (
        float(selected["pe_sell"]["avg_price"]) * abs(int(selected["pe_sell"]["qty"]))
        + float(selected["ce_sell"]["avg_price"]) * abs(int(selected["ce_sell"]["qty"]))
        - float(selected["pe_buy"]["avg_price"]) * abs(int(selected["pe_buy"]["qty"]))
        - float(selected["ce_buy"]["avg_price"]) * abs(int(selected["ce_buy"]["qty"]))
    )
    short_qty = max(
        abs(int(selected["pe_sell"].get("qty", 0))), abs(int(selected["ce_sell"].get("qty", 0)))
    )
    if short_qty <= 0:
        return None

    credit_per_unit = total_credit / short_qty
    pe_raw = float(selected["pe_sell"]["strike"]) - credit_per_unit
    ce_raw = float(selected["ce_sell"]["strike"]) + credit_per_unit
    return {
        "pe": _round_to_nearest_50_tie_down(pe_raw),
        "ce": _round_to_nearest_50_tie_down(ce_raw),
    }


def _break_even_prompt_text(side: str, suggestion: int | None, manual_only: bool = False) -> str:
    side_label = "PE" if side == "pe" else "CE"
    if manual_only or suggestion is None:
        return (
            rf"*Step 5/13 — {side_label} Break\-even*\n\n"
            r"Auto suggestion is blocked because one or more registered legs have missing or zero average price\.\n\n"
            rf"Please enter the {side_label} break\-even strike manually as an integer multiple of 50\."
        )

    return (
        rf"*Step 5/13 — {side_label} Break\-even*\n\n"
        rf"Suggested {side_label} break\-even: *`{suggestion:,}`*\n\n"
        r"You can confirm the suggestion, edit it manually, or skip break\-even for this deployment\."
    )


def _coerce_strike(raw: Any) -> int | None:
    """Best-effort integer strike from deployment / state values."""
    if raw is None or raw == "" or raw == "N/A":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _leg_strike(positions: dict[str, Any] | None, leg_key: str) -> int | None:
    """Read strike from positions.ce_sell / pe_sell without crashing when leg is null."""
    if not isinstance(positions, dict):
        return None
    leg = positions.get(leg_key)
    if not isinstance(leg, dict):
        return None
    return _coerce_strike(leg.get("strike"))


def _buffer_points(raw: Any, default: int = 0) -> int:
    try:
        return int(normalize_buffer_field(raw if raw is not None else default))
    except Exception:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return int(default)


def _wiz_buffer_value(wizard_data: dict[str, Any], typed_key: str, legacy_key: str) -> Decimal:
    raw = wizard_data.get(typed_key)
    if raw is None:
        raw = wizard_data.get(legacy_key, 0)
    return normalize_buffer_field(raw)


def _side_levels(
    selected: dict[str, dict[str, Any] | None], wizard_data: dict[str, Any]
) -> dict[str, int]:
    levels: dict[str, int] = {}
    ce_sell = selected.get("ce_sell")
    pe_sell = selected.get("pe_sell")
    if ce_sell:
        ce_entry = _wiz_buffer_value(
            wizard_data, "wiz_ce_entry_buffer", "wiz_ce_entry_buffer_points"
        )
        ce_exit = _wiz_buffer_value(wizard_data, "wiz_ce_exit_buffer", "wiz_ce_retrace_points")
        levels["ce_trigger"] = int(ce_sell["strike"]) + int(ce_entry)
        levels["ce_retrace"] = int(ce_sell["strike"]) - int(ce_exit)
    if pe_sell:
        pe_entry = _wiz_buffer_value(
            wizard_data, "wiz_pe_entry_buffer", "wiz_pe_entry_buffer_points"
        )
        pe_exit = _wiz_buffer_value(wizard_data, "wiz_pe_exit_buffer", "wiz_pe_retrace_points")
        levels["pe_trigger"] = int(pe_sell["strike"]) - int(pe_entry)
        levels["pe_retrace"] = int(pe_sell["strike"]) + int(pe_exit)
    return levels


def _ato_monitor_keyboard() -> InlineKeyboardMarkup:
    """Step 6/6 — Which ATO sides should the algo automatically manage?"""
    return InlineKeyboardMarkup(
        [
            [
                _btn("\U0001f53b PE side only", f"{_CB_ATO_MON}:pe", style="primary"),
                _btn("\U0001f53a CE side only", f"{_CB_ATO_MON}:ce", style="primary"),
            ],
            [
                _btn("\u26a1 Both sides (recommended)", f"{_CB_ATO_MON}:both", style="success")
            ],
            [_btn("\u274c Cancel", f"{_CB_ATO_MON}:cancel", style="danger")],
        ]
    )


def _compute_trade_window(deploy_date: date) -> dict[str, Any]:
    """Compute known trading days between deploy date and this cycle's expiry."""
    expiry_date = current_week_expiry(expiry_weekday=1, ref=deploy_date)

    auto_working_days: list[date] = []
    d = deploy_date
    while d <= expiry_date:
        if is_trading_day(d):
            auto_working_days.append(d)
        d += timedelta(days=1)

    return {
        "deploy_date": deploy_date,
        "expiry_date": expiry_date,
        "auto_working_days": auto_working_days,
    }


def _holiday_review_keyboard(
    working_days: list[date],
    user_holidays: list[date],
) -> InlineKeyboardMarkup:
    """Build holiday toggle keyboard for Step 7/7 review."""
    holiday_set = set(user_holidays)
    rows: list[list[InlineKeyboardButton]] = []

    for d in working_days:
        is_holiday = d in holiday_set
        prefix = "🚫" if is_holiday else "✅"
        label = f"{prefix} {d.strftime('%a %d-%b')}"
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{_CB_HOL}:toggle:{d.isoformat()}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton("✅ Continue", callback_data=f"{_CB_HOL}:done"),
            InlineKeyboardButton("↺ Clear", callback_data=f"{_CB_HOL}:clear"),
        ]
    )
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_HOL}:cancel")])
    return InlineKeyboardMarkup(rows)


def _render_holiday_review_text(
    deploy_date: date,
    expiry_date: date,
    working_days: list[date],
    user_holidays: list[date],
) -> str:
    """Render Step 7/7 explanatory text with selected holiday impact."""
    holiday_set = set(user_holidays)
    effective_days = [d for d in working_days if d not in holiday_set]

    working_lines = (
        "\n".join(f"• `{d.strftime('%a %d-%b-%Y')}`" for d in working_days) or "• `None`"
    )
    holiday_lines = (
        "\n".join(f"• `{d.strftime('%a %d-%b-%Y')}`" for d in user_holidays) or "• `None selected`"
    )
    effective_lines = (
        "\n".join(f"• `{d.strftime('%a %d-%b-%Y')}`" for d in effective_days) or "• `None`"
    )

    return (
        "*Step 7/7 — Trading Days Review*\n\n"
        f"Deploy date: `{deploy_date.isoformat()}`\n"
        f"Expiry date: `{expiry_date.isoformat()}`\n\n"
        "Auto\\-detected working days \\(weekends and known NSE holidays removed\\):\n"
        f"{working_lines}\n\n"
        "Tap any day below to mark it as an extra holiday for this deployment\\.\n"
        "These days will be excluded from effective reporting calendars\\.\n\n"
        "User\\-marked extra holidays:\n"
        f"{holiday_lines}\n\n"
        "Effective working days after your holiday selection:\n"
        f"{effective_lines}"
    )


def _md2(text: str) -> str:
    """Escape dynamic text for Telegram MarkdownV2."""
    return escape_markdown(str(text), version=2)


def _md2_code(text: str) -> str:
    """Escape dynamic text inside MarkdownV2 inline code spans."""
    return escape_markdown(str(text), version=2, entity_type="code")


async def _reply_md2(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Send MarkdownV2; fall back to plain text if Telegram rejects entities."""
    kwargs: dict[str, Any] = {"parse_mode": ParseMode.MARKDOWN_V2}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    try:
        await message.reply_text(text, **kwargs)
    except BadRequest as exc:
        msg = str(exc).lower()
        if "parse entities" not in msg and "can't parse" not in msg:
            raise
        logger.warning("KAVACH MarkdownV2 reply failed, using plain text: %s", exc)
        plain = text.replace("\\", "")
        kwargs.pop("parse_mode", None)
        await message.reply_text(plain, **kwargs)


async def _edit_md2(
    query: CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit message as MarkdownV2 with plain-text fallback."""
    kwargs: dict[str, Any] = {"parse_mode": ParseMode.MARKDOWN_V2}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        msg = str(exc).lower()
        if "message is not modified" in msg:
            return
        if "parse entities" not in msg and "can't parse" not in msg:
            raise
        logger.warning("KAVACH MarkdownV2 edit failed, using plain text: %s", exc)
        plain = text.replace("\\", "")
        kwargs.pop("parse_mode", None)
        await query.edit_message_text(plain, **kwargs)


async def _on_handler_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log handler failures and nudge operator back to the menu."""
    err = context.error
    logger.error("KAVACH handler error: %s", err, exc_info=err)
    if not isinstance(update, Update):
        return
    message = update.effective_message
    if message is None:
        return
    try:
        await _reply_md2(
            message,
            r"⚠️ Something went wrong\. Tap *Status* or send /start to return to the menu\.",
            reply_markup=_main_menu_keyboard(),
        )
    except Exception:
        pass


async def _safe_answer_callback(
    query: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> bool:
    """Answer a callback query; return False if the query is already expired."""
    try:
        await query.answer(text=text, show_alert=show_alert)
        return True
    except BadRequest as exc:
        msg = str(exc).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            logger.warning("Stale callback query ignored: %s", exc)
            return False
        raise


def _wizard_plain_fallback(text: str) -> str:
    """Strip MarkdownV2 escapes for plain-text Telegram fallback."""
    return text.replace("\\", "")


async def _wizard_show(
    context: ContextTypes.DEFAULT_TYPE,
    target: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    prefer_edit: bool = False,
) -> Message:
    """Show wizard UI — edit in place when possible to avoid stale button rows."""
    kwargs: dict[str, Any] = {"parse_mode": ParseMode.MARKDOWN_V2}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup

    wizard_data = _wizard_data(context)
    if prefer_edit:
        try:
            await target.edit_text(text, **kwargs)
            wizard_data["wiz_ui_message_id"] = target.message_id
            return target
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                wizard_data["wiz_ui_message_id"] = target.message_id
                return target
            logger.warning("Wizard edit failed, sending new message: %s", exc)

    try:
        sent = await target.reply_text(text, **kwargs)
    except BadRequest as exc:
        logger.warning("Wizard MarkdownV2 reply failed, using plain text: %s", exc)
        plain_kwargs = {k: v for k, v in kwargs.items() if k != "parse_mode"}
        sent = await target.reply_text(_wizard_plain_fallback(text), **plain_kwargs)
    wizard_data["wiz_ui_message_id"] = sent.message_id
    return sent


async def _wizard_edit_step(
    context: ContextTypes.DEFAULT_TYPE,
    query: CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the active wizard message; fall back to a fresh reply if needed."""
    kwargs: dict[str, Any] = {"parse_mode": ParseMode.MARKDOWN_V2}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    plain_kwargs = {k: v for k, v in kwargs.items() if k != "parse_mode"}
    plain_text = _wizard_plain_fallback(text)

    message = query.message
    if message is None:
        return

    try:
        await query.edit_message_text(text, **kwargs)
        _wizard_data(context)["wiz_ui_message_id"] = message.message_id
        return
    except BadRequest as exc:
        msg = str(exc).lower()
        if "message is not modified" in msg:
            return
        if "can't parse entities" in msg or "parse entities" in msg:
            try:
                await query.edit_message_text(plain_text, **plain_kwargs)
                _wizard_data(context)["wiz_ui_message_id"] = message.message_id
                return
            except BadRequest:
                pass
        logger.warning("Wizard step edit failed, sending new message: %s", exc)

    chat_id = message.chat_id
    ui_message_id = _wizard_data(context).get("wiz_ui_message_id")
    if ui_message_id and ui_message_id != message.message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=ui_message_id,
                text=text,
                **kwargs,
            )
            return
        except BadRequest as exc:
            if "can't parse entities" in str(exc).lower() or "parse entities" in str(exc).lower():
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=ui_message_id,
                        text=plain_text,
                        **plain_kwargs,
                    )
                    return
                except BadRequest:
                    pass

    try:
        sent = await message.reply_text(text, **kwargs)
    except BadRequest as exc:
        logger.warning("Wizard MarkdownV2 fallback reply: %s", exc)
        sent = await message.reply_text(plain_text, **plain_kwargs)
    _wizard_data(context)["wiz_ui_message_id"] = sent.message_id



def _selected_header(selected: dict[str, dict]) -> str:
    """Build the confirmation header for wizard steps."""
    order = [
        "pe_buy",
        "pe_margin_hedge",
        "pe_dyn_hedge",
        "pe_sell",
        "ce_buy",
        "ce_margin_hedge",
        "ce_dyn_hedge",
        "ce_sell",
    ]
    labels = {
        "pe_buy": "Core PE BUY",
        "pe_margin_hedge": "Margin Hedge PE",
        "pe_dyn_hedge": "30% Dyn Hedge PE",
        "pe_sell": "PE SELL",
        "ce_buy": "Core CE BUY",
        "ce_margin_hedge": "Margin Hedge CE",
        "ce_dyn_hedge": "30% Dyn Hedge CE",
        "ce_sell": "CE SELL",
    }
    return "\n".join(
        f"✅ {_md2(labels[k])}: {_md2(selected[k]['symbol'])}" for k in order if k in selected
    )


def _write_deployment_file(
    selected: dict[str, dict | None],
    registration_scope: dict[str, Any],
    *,
    ato_step: int = 50,
    ce_entry_buffer: Any = 0,
    pe_entry_buffer: Any = 0,
    ce_retrace_buffer: Any = 5,
    pe_retrace_buffer: Any = 5,
    poll_interval_seconds: int | None = None,
    ato_manage_sides: str = "both",
    pe_protect_strike: int | None = None,
    pe_protect_symbol: str | None = None,
    pe_protect_strike_mode: str | None = None,
    ce_protect_strike: int | None = None,
    ce_protect_symbol: str | None = None,
    ce_protect_strike_mode: str | None = None,
    break_even: dict[str, Any] | None = None,
    trading_calendar: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    order_mode: str = "paper",
) -> Path:
    """Write batman_YYYY-MM-DD_HH-MM.json and return its path."""
    _DEPLOY_DIR.mkdir(parents=True, exist_ok=True)

    ce_entry_dec = normalize_buffer_field(ce_entry_buffer)
    pe_entry_dec = normalize_buffer_field(pe_entry_buffer)
    ce_retrace_dec = normalize_buffer_field(ce_retrace_buffer)
    pe_retrace_dec = normalize_buffer_field(pe_retrace_buffer)
    retrace_points = legacy_int_from_buffer(ce_retrace_buffer, default=5)

    def _typed(raw: Any, dec: Decimal) -> dict[str, str]:
        if isinstance(raw, dict) and raw.get("type"):
            return raw
        kind = BufferKind.CUSTOM if str(dec) != str(int(dec)) else BufferKind.PREDEFINED
        return serialize_buffer_field(dec, kind)

    pe_sell = selected.get("pe_sell")
    ce_sell = selected.get("ce_sell")
    pe_ato_sym = pe_ato_strike = ce_ato_sym = ce_ato_strike = None
    if pe_sell:
        pe_ato_strike = (
            int(pe_protect_strike)
            if pe_protect_strike is not None
            else int(pe_sell["strike"]) - ato_step
        )
        pe_ato_sym = pe_protect_symbol or build_ato_protect_symbol(
            pe_sell["symbol"], pe_ato_strike, "PE"
        )
    if ce_sell:
        ce_ato_strike = (
            int(ce_protect_strike)
            if ce_protect_strike is not None
            else int(ce_sell["strike"]) + ato_step
        )
        ce_ato_sym = ce_protect_symbol or build_ato_protect_symbol(
            ce_sell["symbol"], ce_ato_strike, "CE"
        )

    now = datetime.now()
    filename = f"batman_{now.strftime('%Y-%m-%d_%H-%M')}.json"
    filepath = _DEPLOY_DIR / filename

    from core.order_mode import normalize_order_mode

    omode = normalize_order_mode(order_mode)
    data: dict[str, Any] = {
        "schema_version": 1.1,
        "order_mode": omode,
        "deployed_at": now.astimezone().isoformat(),
        "registered_at": now.strftime("%A %d-%b-%Y at %H:%M"),
        "file_name": filename,
        "expiry_weekday": 1,
        "retrace_points": retrace_points,
        "ato_manage_sides": ato_manage_sides,
        "registration_scope": registration_scope,
        "positions": {
            "pe_buy": selected.get("pe_buy"),
            "pe_margin_hedge": selected.get("pe_margin_hedge"),
            "pe_dyn_hedge": selected.get("pe_dyn_hedge"),
            "pe_sell": pe_sell,
            "ce_buy": selected.get("ce_buy"),
            "ce_margin_hedge": selected.get("ce_margin_hedge"),
            "ce_dyn_hedge": selected.get("ce_dyn_hedge"),
            "ce_sell": ce_sell,
        },
        "ato": {
            "pe_protect_symbol": pe_ato_sym,
            "pe_protect_strike": pe_ato_strike,
            "pe_protect_strike_mode": pe_protect_strike_mode,
            "ce_protect_symbol": ce_ato_sym,
            "ce_protect_strike": ce_ato_strike,
            "ce_protect_strike_mode": ce_protect_strike_mode,
            "ato_step": ato_step,
            "retrace_points": retrace_points,
            "ce_entry_buffer": _typed(ce_entry_buffer, ce_entry_dec),
            "pe_entry_buffer": _typed(pe_entry_buffer, pe_entry_dec),
            "ce_retrace_buffer": _typed(ce_retrace_buffer, ce_retrace_dec),
            "pe_retrace_buffer": _typed(pe_retrace_buffer, pe_retrace_dec),
            "ce_entry_buffer_points": legacy_int_from_buffer(ce_entry_buffer),
            "pe_entry_buffer_points": legacy_int_from_buffer(pe_entry_buffer),
            "ce_retrace_points": legacy_int_from_buffer(ce_retrace_buffer, default=retrace_points),
            "pe_retrace_points": legacy_int_from_buffer(pe_retrace_buffer, default=retrace_points),
            "poll_interval_seconds": poll_interval_seconds,
        },
        "status": "armed",
    }

    if break_even:
        data["risk"] = {
            "break_even": {
                "pe": break_even.get("pe"),
                "ce": break_even.get("ce"),
                "rounding_rule": "nearest_50_tie_down",
                "skipped": bool(break_even.get("skipped", False)),
            }
        }

    if trading_calendar:
        data["calendar"] = trading_calendar

    if profile:
        data["profile"] = profile

    try:
        from core.ato_working_profile import apply_working_profile_to_deploy

        if apply_working_profile_to_deploy(data):
            logger.info(
                "ATO working profile applied to new deployment (%s)",
                data.get("ato_manage_sides"),
            )
    except Exception as exc:
        logger.warning("ATO working profile apply on write skipped: %s", exc)

    with open(filepath, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)

    logger.info("Deployment file written: %s", filepath)
    return filepath


def _state_reset(state) -> None:
    """Clear all deployment-related keys in StateManager."""
    if state is None:
        return
    nones = [
        "positions.ce_sell",
        "positions.ce_buy",
        "positions.ce_margin_hedge",
        "positions.ce_dyn_hedge",
        "positions.pe_sell",
        "positions.pe_buy",
        "positions.pe_margin_hedge",
        "positions.pe_dyn_hedge",
        "ato.ce_protect_symbol",
        "ato.ce_protect_strike",
        "ato.pe_protect_symbol",
        "ato.pe_protect_strike",
        "ato.ce_order_id",
        "ato.pe_order_id",
        "dyn_hedge.pe_exited_date",
        "dyn_hedge.ce_exited_date",
    ]
    for key in nones:
        state.set(key, None, save=False)
    state.set("ato.ce_triggered", False, save=False)
    state.set("ato.pe_triggered", False, save=False)
    state.set("ato.ce_ato_active", False, save=False)
    state.set("ato.pe_ato_active", False, save=False)
    state.set("ato.ce_awaiting_clearance", False, save=False)
    state.set("ato.pe_awaiting_clearance", False, save=False)
    state.set("ato.retrace_points", 5, save=False)
    state.set("ato.manage_sides", "both", save=False)
    state.set("ato.ce_entry_buffer_points", 0, save=False)
    state.set("ato.pe_entry_buffer_points", 0, save=False)
    state.set("ato.ce_retrace_points", 5, save=False)
    state.set("ato.pe_retrace_points", 5, save=False)
    state.set("ato.poll_interval_seconds", None, save=False)
    state.set("risk.break_even.pe", None, save=False)
    state.set("risk.break_even.ce", None, save=False)
    state.set("risk.break_even.confirmed", False, save=False)
    state.set("risk.break_even.source.pe", None, save=False)
    state.set("risk.break_even.source.ce", None, save=False)
    state.set("risk.break_even.skipped", False, save=False)
    state.set("modules.ratripal.enabled", False, save=False)
    state.set("modules.aditya.enabled", False, save=False)
    state.set("ratripal.last_run_date", None, save=False)
    state.set("ratripal.last_decision", None, save=False)
    state.set("ratripal.pending.request_id", None, save=False)
    state.set("ratripal.pending.response", None, save=False)
    state.set("ratripal.pending.sent_at", None, save=False)
    state.set("aditya.handoff_file", None, save=False)
    state.set("deployment.confirmed", False, save=False)
    state.set("deployment.file", None, save=False)
    state.set("deployment.registration_scope", None, save=False)
    state.set("deployment.batman_complete", True, save=False)
    state.set("session.emergency_exited", False, save=False)
    state.set("ato.ce_side_halted", False, save=False)
    state.set("ato.pe_side_halted", False, save=False)
    state.set("ato.ce_halt_reason", None, save=False)
    state.set("ato.pe_halt_reason", None, save=False)
    state.set("deployment.cleanup_failed", False, save=False)
    state.set("dyn_hedge.exit_enabled", False, save=False)


def _clear_wizard_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Drop all temporary wizard keys to prevent stale data reuse."""
    user_data = context.user_data
    if user_data is None:
        return
    wizard_keys = (
        "wiz_positions",
        "wiz_selected",
        "wiz_ui_message_id",
        "pe_enabled",
        "ce_enabled",
        "pe_buy",
        "pe_margin_hedge",
        "pe_dyn_hedge",
        "pe_sell",
        "ce_buy",
        "ce_margin_hedge",
        "ce_dyn_hedge",
        "ce_sell",
        "pe_managed_lots",
        "ce_managed_lots",
        "pe_ato_lots",
        "ce_ato_lots",
        "pe_protect_strike",
        "ce_protect_strike",
        "pe_protect_symbol",
        "ce_protect_symbol",
        "pe_protect_strike_mode",
        "ce_protect_strike_mode",
        "wiz_plan",
        "_pe_ato_suggested",
        "_ce_ato_suggested",
        "_pe_pick_pool",
        "_ce_pick_pool",
        "_pe_hedge_pool",
        "_ce_hedge_pool",
        "_pe_max_lots",
        "_ce_max_lots",
        "_buf_custom_target",
        "wiz_registration_scope",
    )
    for key in wizard_keys:
        user_data.pop(key, None)
    for key in list(user_data):
        if isinstance(key, str) and key.startswith("wiz_"):
            user_data.pop(key, None)


def _derive_ato_protect_fields(positions: dict[str, Any], ato: dict[str, Any]) -> dict[str, Any]:
    """Ensure protect symbol/strike exist — derive from sell legs when JSON has null."""
    ato_step = int(ato.get("ato_step", 50))
    out = dict(ato)
    ce_sell = positions.get("ce_sell")
    if ce_sell and not out.get("ce_protect_symbol"):
        strike = int(out.get("ce_protect_strike") or int(ce_sell.get("strike", 0)) + ato_step)
        out["ce_protect_symbol"] = build_ato_protect_symbol(
            str(ce_sell.get("symbol", "")), strike, "CE"
        )
        out["ce_protect_strike"] = strike
    pe_sell = positions.get("pe_sell")
    if pe_sell and not out.get("pe_protect_symbol"):
        strike = int(out.get("pe_protect_strike") or int(pe_sell.get("strike", 0)) - ato_step)
        out["pe_protect_symbol"] = build_ato_protect_symbol(
            str(pe_sell.get("symbol", "")), strike, "PE"
        )
        out["pe_protect_strike"] = strike
    return out


def _ato_lots_warning_lines(
    wizard_data: dict[str, Any],
    selected: dict[str, dict | None],
    lot_size: int,
) -> list[str]:
    """Warnings when operator ATO lots exceed managed or broker BUY lots."""
    lines: list[str] = []
    if wizard_data.get("pe_enabled"):
        ato_lots = wizard_data.get("pe_ato_lots")
        if ato_lots is not None:
            managed = int(wizard_data.get("pe_managed_lots") or 0)
            if int(ato_lots) > managed:
                lines.append(
                    f"⚠️ PE ATO lots \\({ato_lots}\\) exceed managed BUY lots \\({managed}\\)"
                )
            buy_leg = selected.get("pe_buy")
            if buy_leg:
                broker_lots = broker_buy_lots(buy_leg, lot_size=lot_size)
                if int(ato_lots) > broker_lots:
                    lines.append(
                        f"⚠️ PE ATO lots \\({ato_lots}\\) exceed broker BUY lots \\({broker_lots}\\)"
                    )
    if wizard_data.get("ce_enabled"):
        ato_lots = wizard_data.get("ce_ato_lots")
        if ato_lots is not None:
            managed = int(wizard_data.get("ce_managed_lots") or 0)
            if int(ato_lots) > managed:
                lines.append(
                    f"⚠️ CE ATO lots \\({ato_lots}\\) exceed managed BUY lots \\({managed}\\)"
                )
            buy_leg = selected.get("ce_buy")
            if buy_leg:
                broker_lots = broker_buy_lots(buy_leg, lot_size=lot_size)
                if int(ato_lots) > broker_lots:
                    lines.append(
                        f"⚠️ CE ATO lots \\({ato_lots}\\) exceed broker BUY lots \\({broker_lots}\\)"
                    )
    return lines


def _economy_profile_flags(
    wizard_data: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any]:
    """SARANSH / reporting tag for custom or partial ATO setups."""
    custom = False
    partial = False
    if wizard_data.get("pe_enabled"):
        if wizard_data.get("pe_protect_strike_mode") == "CUSTOM":
            custom = True
        pe_ml = wizard_data.get("pe_managed_lots")
        pe_al = wizard_data.get("pe_ato_lots")
        if pe_ml is not None and pe_al is not None and int(pe_al) < int(pe_ml):
            partial = True
    if wizard_data.get("ce_enabled"):
        if wizard_data.get("ce_protect_strike_mode") == "CUSTOM":
            custom = True
        ce_ml = wizard_data.get("ce_managed_lots")
        ce_al = wizard_data.get("ce_ato_lots")
        if ce_ml is not None and ce_al is not None and int(ce_al) < int(ce_ml):
            partial = True
    economy = custom
    return {
        "custom_ato_economy_profile": economy,
        "custom_protect_strike": custom,
        "partial_ato_lots": partial,
    }


def _orphan_leg_warning_lines(
    context: ContextTypes.DEFAULT_TYPE,
    wizard_data: dict[str, Any],
    selected: dict[str, dict | None],
) -> list[str]:
    """Q59 — warn on orphan long legs outside new registration scope."""
    from core.ato_orphan_legs import detect_orphan_long_legs, registered_symbol_set

    broker = context.bot_data.get("broker")
    if not broker:
        return []
    try:
        df = broker.get_positions()
        positions = _enrich_positions_list(context, _filter_nifty_positions(df))
    except Exception as exc:
        logger.warning("Orphan leg scan skipped: %s", exc)
        return []

    ato_step = int(
        (context.bot_data.get("params", {}).get("deploy_wizard") or {}).get("ato_step", 50)
    )
    ce_protect = None
    pe_protect = None
    if wizard_data.get("ce_enabled") and selected.get("ce_sell"):
        ce_sell = selected["ce_sell"]
        ce_strike = int(
            wizard_data.get("ce_protect_strike")
            or auto_protect_strike(int(ce_sell["strike"]), "CE", ato_step=ato_step)
        )
        ce_protect = str(
            wizard_data.get("ce_protect_symbol")
            or build_ato_protect_symbol(ce_sell["symbol"], ce_strike, "CE")
        )
    if wizard_data.get("pe_enabled") and selected.get("pe_sell"):
        pe_sell = selected["pe_sell"]
        pe_strike = int(
            wizard_data.get("pe_protect_strike")
            or auto_protect_strike(int(pe_sell["strike"]), "PE", ato_step=ato_step)
        )
        pe_protect = str(
            wizard_data.get("pe_protect_symbol")
            or build_ato_protect_symbol(pe_sell["symbol"], pe_strike, "PE")
        )

    registered = registered_symbol_set(
        selected,
        ce_protect_symbol=ce_protect,
        pe_protect_symbol=pe_protect,
    )
    orphan_msgs = detect_orphan_long_legs(positions, registered)
    return [f"⚠️ Orphan leg: {_md2(msg)}" for msg in orphan_msgs]


def _validate_protect_strikes_at_confirm(
    wizard_data: dict[str, Any],
    selected: dict[str, dict | None],
) -> list[str]:
    from core.strike_validation import validate_protect_strike_exists

    errors: list[str] = []
    if wizard_data.get("pe_enabled") and selected.get("pe_sell"):
        strike = wizard_data.get("pe_protect_strike")
        if strike is not None:
            ok, err = validate_protect_strike_exists(
                side="PE",
                protect_strike=int(strike),
                sell_leg=selected["pe_sell"],
            )
            if not ok and err:
                errors.append(err)
    if wizard_data.get("ce_enabled") and selected.get("ce_sell"):
        strike = wizard_data.get("ce_protect_strike")
        if strike is not None:
            ok, err = validate_protect_strike_exists(
                side="CE",
                protect_strike=int(strike),
                sell_leg=selected["ce_sell"],
            )
            if not ok and err:
                errors.append(err)
    return errors


def _protect_strike_warning_lines(
    wizard_data: dict[str, Any],
    selected: dict[str, dict | None],
) -> list[str]:
    lines: list[str] = []
    if wizard_data.get("pe_enabled") and selected.get("pe_sell"):
        strike = wizard_data.get("pe_protect_strike")
        if strike is not None:
            for msg in protect_strike_direction_warnings(
                "PE", int(selected["pe_sell"]["strike"]), int(strike)
            ):
                lines.append(f"⚠️ {_md2(msg)}")
        mode = wizard_data.get("pe_protect_strike_mode")
        if mode == "CUSTOM":
            lines.append(
                "⚠️ PE ATO uses a *custom* protect strike \\(economy / reduced hedge\\)\\."
            )
    if wizard_data.get("ce_enabled") and selected.get("ce_sell"):
        strike = wizard_data.get("ce_protect_strike")
        if strike is not None:
            for msg in protect_strike_direction_warnings(
                "CE", int(selected["ce_sell"]["strike"]), int(strike)
            ):
                lines.append(f"⚠️ {_md2(msg)}")
        mode = wizard_data.get("ce_protect_strike_mode")
        if mode == "CUSTOM":
            lines.append(
                "⚠️ CE ATO uses a *custom* protect strike \\(economy / reduced hedge\\)\\."
            )
    return lines


def _sync_state_from_deployment_file(filepath: Path, state) -> None:
    """Load confirmed deployment JSON into runtime state for immediate activation."""
    if state is None:
        return

    with open(filepath, encoding="utf-8") as fh:
        dep = json.load(fh)

    positions = dep.get("positions", {})
    ato = _derive_ato_protect_fields(positions, dep.get("ato", {}))
    scope = legacy_registration_scope_from_deployment(dep)

    for role, leg in positions.items():
        state.set(f"positions.{role}", leg, save=False)

    state.set("deployment.registration_scope", scope, save=False)
    state.set("ato.ce_protect_symbol", ato.get("ce_protect_symbol"), save=False)
    state.set("ato.ce_protect_strike", ato.get("ce_protect_strike"), save=False)
    state.set("ato.pe_protect_symbol", ato.get("pe_protect_symbol"), save=False)
    state.set("ato.pe_protect_strike", ato.get("pe_protect_strike"), save=False)
    state.set("ato.retrace_points", dep.get("retrace_points", 5), save=False)
    state.set("ato.manage_sides", dep.get("ato_manage_sides", "both"), save=False)

    ce_entry = ato.get("ce_entry_buffer", ato.get("ce_entry_buffer_points", 0))
    pe_entry = ato.get("pe_entry_buffer", ato.get("pe_entry_buffer_points", 0))
    ce_retrace = ato.get(
        "ce_retrace_buffer", ato.get("ce_retrace_points", dep.get("retrace_points", 5))
    )
    pe_retrace = ato.get(
        "pe_retrace_buffer", ato.get("pe_retrace_points", dep.get("retrace_points", 5))
    )

    state.set("ato.ce_entry_buffer_points", normalize_buffer_field(ce_entry), save=False)
    state.set("ato.pe_entry_buffer_points", normalize_buffer_field(pe_entry), save=False)
    state.set("ato.ce_retrace_points", normalize_buffer_field(ce_retrace), save=False)
    state.set("ato.pe_retrace_points", normalize_buffer_field(pe_retrace), save=False)
    state.set("ato.poll_interval_seconds", ato.get("poll_interval_seconds"), save=False)

    # Same proven ATO recipe in UAT and live (prod) after deploy confirm.
    try:
        from core.ato_working_profile import (
            apply_working_profile_to_deploy,
            apply_working_profile_to_state,
        )

        apply_working_profile_to_deploy(dep)
        apply_working_profile_to_state(state, save=False, for_deploy=True)
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(dep, fh, indent=2, default=str)
    except Exception as exc:
        logger.warning("ATO working profile apply on deploy skipped: %s", exc)
    break_even = dep.get("risk", {}).get("break_even", {})
    state.set("risk.break_even.pe", break_even.get("pe"), save=False)
    state.set("risk.break_even.ce", break_even.get("ce"), save=False)
    state.set(
        "risk.break_even.confirmed",
        bool(break_even.get("pe") is not None and break_even.get("ce") is not None),
        save=False,
    )
    state.set("risk.break_even.skipped", bool(break_even.get("skipped", False)), save=False)
    # RATRIPAL uses fixed sell±200 BE — enable whenever core sell legs exist.
    positions = dep.get("positions") or {}
    has_sell = bool(positions.get("pe_sell") or positions.get("ce_sell"))
    state.set("modules.ratripal.enabled", has_sell, save=False)
    state.set("modules.aditya.enabled", False, save=False)

    # 30% Dynamic Hedge: auto-arm exit when Register persisted dyn legs.
    # Operator can still turn OFF via menu; do not leave legs stranded at default No.
    has_dyn = bool(positions.get("pe_dyn_hedge") or positions.get("ce_dyn_hedge"))
    state.set("dyn_hedge.pe_exited_date", None, save=False)
    state.set("dyn_hedge.ce_exited_date", None, save=False)
    state.set("dyn_hedge.exit_enabled", has_dyn, save=False)

    state.set("ato.ce_triggered", False, save=False)
    state.set("ato.pe_triggered", False, save=False)
    state.set("ato.ce_ato_active", False, save=False)
    state.set("ato.pe_ato_active", False, save=False)
    state.set("ato.ce_awaiting_clearance", False, save=False)
    state.set("ato.pe_awaiting_clearance", False, save=False)
    state.set("deployment.confirmed", True, save=False)
    state.set("deployment.batman_complete", False, save=False)
    state.set("deployment.file", str(filepath), save=False)
    state.set("algo.paused", False, save=False)
    state.set("session.emergency_exited", False)
    state.save()


def _finalize_register_confirm(
    context: ContextTypes.DEFAULT_TYPE,
    filepath: Path,
    wizard_data: dict[str, Any],
    selected: dict[str, Any],
    poll_interval_seconds: int | None,
    ato_manage_sides: str,
) -> None:
    with deployment_session("register_confirm"):
        _mirror_deployment_to_daily_audit(filepath)
        state = context.bot_data.get("state")
        _sync_state_from_deployment_file(filepath, state)
        _persist_session_after_confirm(filepath, state)
        _append_log(
            "confirmed",
            file=filepath.name,
            pe_enabled=wizard_data.get("pe_enabled"),
            ce_enabled=wizard_data.get("ce_enabled"),
            poll_interval_seconds=poll_interval_seconds,
            ato_manage_sides=ato_manage_sides,
        )
        bus = context.bot_data.get("event_bus")
        if bus:
            from core.event_bus import Event

            bus.publish(Event.DEPLOYMENT_CONFIRMED, {"file": str(filepath)})
        try:
            from core.saransh_session_sync import saransh_session_arm

            saransh_session_arm(
                deployment_file=filepath.name,
                restart_reason="register_confirm",
            )
        except Exception as exc:
            logger.warning("SARANSH session arm soft-failed: %s", exc)


def _persist_session_after_confirm(filepath: Path, state) -> None:
    """Atomic UAT session bundle after register confirm."""
    try:
        from core.batman_mode import get_mode, shadow_ledger_path, workspace_root
        from core.session_bundle import persist_uat_session_bundle

        root = workspace_root()
        if get_mode(root) != "uat" or state is None:
            return
        shadow = shadow_ledger_path(root)
        payload = json.loads(Path(state._path).read_text(encoding="utf-8"))
        persist_uat_session_bundle(
            root=root,
            state_path=Path(state._path),
            state_payload=payload,
            shadow_ledger_path=shadow,
            deployment_path=filepath,
        )
    except Exception as exc:
        logger.warning("Session bundle persist skipped: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# Deploy Wizard — ConversationHandler
# ═══════════════════════════════════════════════════════════════════════════════

WIZARD_CONVERSATION_NAME = WIZARD_CONVERSATION_NAME  # re-export from register_wizard


def _register_conversation_key(update: Update) -> tuple[str, int, int] | None:
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return None
    return (WIZARD_CONVERSATION_NAME, chat.id, user.id)


def _set_register_conversation_state(
    context: ContextTypes.DEFAULT_TYPE, update: Update, state_id: int
) -> None:
    """Attach Register ConversationHandler state after Batman Complete auto-start.

    Writing only ``user_data[(name, chat, user)]`` does **not** work on PTB —
    the live state lives on ``ConversationHandler._conversations``.
    """
    from telegram.ext import ConversationHandler

    app = context.application
    key: tuple | None = None
    for group_handlers in app.handlers.values():
        for handler in group_handlers:
            if not isinstance(handler, ConversationHandler):
                continue
            if handler.name != WIZARD_CONVERSATION_NAME:
                continue
            try:
                key = handler._get_key(update)
            except Exception:
                chat = update.effective_chat
                user = update.effective_user
                if chat is not None and user is not None:
                    key = (chat.id, user.id)
            if key is None:
                logger.warning("KAVACH2: cannot build conversation key for register state")
                return
            if state_id == ConversationHandler.END:
                handler._conversations.pop(key, None)
            else:
                handler._conversations[key] = state_id
            logger.info(
                "KAVACH2: register conversation state set → %s key=%s", state_id, key
            )
            return
    logger.warning("KAVACH2: register ConversationHandler not found — buttons may not respond")


def _is_batman_armed(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Armed only when a live deployment file exists.

    A leftover ``deployment.confirmed=True`` after the file was archived used to
    block Register while the alive card still showed \"Not deployed\".
    """
    if _find_active_deployment() is not None:
        return True
    state = context.bot_data.get("state")
    if state and state.get("deployment.confirmed", False):
        try:
            state.set("deployment.confirmed", False, save=False)
            state.set("deployment.file", None, save=False)
            state.save()
            logger.warning(
                "KAVACH2: healed ghost deployment.confirmed (no active batman_*.json)"
            )
        except Exception as exc:
            logger.warning("KAVACH2: ghost armed heal failed: %s", exc)
    return False


def _try_bootstrap_uat_broker(context: ContextTypes.DEFAULT_TYPE):
    """UAT /register: ShadowBroker from fixture even when startup had no broker."""
    from dotenv import dotenv_values

    from core.batman_mode import access_token_path, is_uat, secrets_dhan_env_path, workspace_root
    from core.broker_factory import create_broker
    from core.token_store import TokenStore

    if not is_uat():
        return None
    root = workspace_root()
    env_path = secrets_dhan_env_path(root)
    if not env_path.is_file():
        env_path = root / "config" / ".env"
    env = dotenv_values(env_path)
    client_code = (env.get("DHAN_CLIENT_CODE") or "").strip()
    if not client_code:
        return None
    store = TokenStore(path=access_token_path(root))
    token, _ = store.load()
    if not token:
        return None
    try:
        from core.uat_positions import load_positions_fixture

        load_positions_fixture(root)
    except Exception:
        return None
    try:
        broker = create_broker(client_code, token, root)
    except Exception as exc:
        logger.warning("UAT register broker bootstrap failed: %s", exc)
        return None
    context.bot_data["broker"] = broker
    try:
        from core.broker_factory import apply_runtime_mode_provider

        state = context.bot_data.get("state")
        if state is not None:
            apply_runtime_mode_provider(broker, state)
    except Exception:
        pass
    logger.info("UAT register: ShadowBroker bootstrapped from fixture book")
    return broker


async def _register_gate_block(
    context: ContextTypes.DEFAULT_TYPE,
    message,
    *,
    prefer_edit: bool = False,
) -> int | None:
    """Return ConversationHandler.END when register must not proceed."""
    state = context.bot_data.get("state")
    if state and state.get("deployment.cleanup_failed", False):
        await _wizard_show(
            context,
            message,
            "⚠️ *Cleanup incomplete*\n\n"
            "Batman Complete did not verify cleanly after retries\\.\n"
            "Resolve cleanup issues before registering again\\.",
            prefer_edit=prefer_edit,
        )
        return ConversationHandler.END

    if _is_batman_armed(context):
        await _wizard_show(
            context,
            message,
            "⚠️ *Batman is armed*\n\n"
            "Tap *Batman Complete* first\\. After verified cleanup, "
            "registration will start automatically\\.",
            prefer_edit=prefer_edit,
        )
        return ConversationHandler.END
    return None


async def wizard_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /register (or /deploy alias)."""
    if not await guard_paused_command(
        update,
        context,
        bot_name="kavach2",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return ConversationHandler.END

    # Prevent double Environment + double Question 1 when:
    # - two getUpdates clients race the same Register tap (Telegram 409), or
    # - allow_reentry + concurrent tap / Batman Complete auto-start overlap.
    import time as _time

    now = _time.monotonic()
    last = float(context.application.bot_data.get("_register_entry_mono") or 0.0)
    if now - last < 8.0:
        logger.warning(
            "Register entry ignored — duplicate within %.1fs (anti double-wizard)",
            now - last,
        )
        return ConversationHandler.END
    context.application.bot_data["_register_entry_mono"] = now

    # Drop any previous wizard keyboard so stale PE BUY buttons cannot be tapped.
    prev_ui = (_wizard_data(context) or {}).get("wiz_ui_message_id")
    message = _require_message(update)
    if prev_ui and message is not None:
        try:
            await context.bot.delete_message(chat_id=message.chat_id, message_id=int(prev_ui))
        except Exception:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=message.chat_id, message_id=int(prev_ui), reply_markup=None
                )
            except Exception:
                pass

    prefer_edit = bool(context.user_data.pop("_register_prefer_edit", False))
    _clear_wizard_data(context)
    try:
        from core.saransh_session_sync import saransh_session_reset_feeds_only

        saransh_session_reset_feeds_only()
    except Exception as exc:
        logger.warning("SARANSH register feed reset soft-failed: %s", exc)
    # ── Token gate — DRISHTI must have supplied a live Dhan token (prod/dev) ─
    broker = context.bot_data.get("broker")
    from core.batman_mode import is_uat, workspace_root

    if is_uat() and broker is None:
        broker = _try_bootstrap_uat_broker(context)

    uat_virtual = is_uat() and broker is not None and type(broker).__name__ == "ShadowBroker"
    if not uat_virtual and (not broker or broker.token_age_hours >= 24):
        hint = (
            "Token has expired — send a fresh Dhan JWT to *DRISHTI* first\\."
            if broker
            else "No Dhan access token — open *DRISHTI* and send your JWT\\."
        )
        await message.reply_text(
            f"🔒 *Token Required*\n\n{hint}\n\n"
            "_Batman cannot fetch positions without a live broker connection\\._",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        _append_log("wizard_cancelled", reason="no_valid_token")
        _clear_wizard_data(context)
        return ConversationHandler.END

    blocked = await _register_gate_block(context, message, prefer_edit=prefer_edit)
    if blocked is not None:
        return blocked

    # ── First question: Paper vs Live (rest of wizard unchanged after this) ──
    from bat_telegram.bots.kavach2.register_wizard import _CB_ORDER_MODE
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    mode_kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📄 Paper trade (no exchange orders)",
                    callback_data=f"{_CB_ORDER_MODE}:paper",
                )
            ],
            [
                InlineKeyboardButton(
                    "💰 Live trade (real Dhan orders)",
                    callback_data=f"{_CB_ORDER_MODE}:live",
                )
            ],
        ]
    )
    body = (
        "🦇 *" + _md2("Register - Trading mode") + "*\n\n"
        + _md2("How should this deployment place orders?") + "\n\n"
        + "• *Paper trade* — " + _md2("Live market data; Kavach/ATO fully runs; no exchange orders.") + "\n"
        + "• *Live trade* — " + _md2("Real money on Dhan (existing live order path).") + "\n\n"
        + "_" + _md2("Everything after this question is the same as before.") + "_"
    )
    await message.reply_text(
        body,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=mode_kb,
    )
    return WIZARD_ORDER_MODE


async def _wizard_continue_after_order_mode(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Resume classic /register flow after Paper/Live is chosen."""
    query = update.callback_query
    message = query.message if query is not None else _require_message(update)
    prefer_edit = bool(context.user_data.pop("_register_prefer_edit", False))
    broker = context.bot_data.get("broker")
    from core.batman_mode import is_uat, workspace_root
    from core.environment_display import register_preamble

    mode = str(_wizard_data(context).get("order_mode") or "paper").upper()
    mode_line = f"Mode: *{_md2(mode)}*\n\n"
    if query is not None:
        try:
            await query.edit_message_text(
                mode_line + register_preamble(),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            await message.reply_text(
                mode_line + register_preamble(),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
    else:
        await message.reply_text(
            mode_line + register_preamble(),
            parse_mode=ParseMode.MARKDOWN_V2,
        )


    try:
        from core.uat_ingest import (
            UATIngestError,
            ingest_uat_for_register,
            publish_uat_ingest_failure,
        )
        from core.uat_register_cleanup import prepare_uat_register_fresh

        if is_uat():
            root = workspace_root()
            state = context.bot_data.get("state")
            cleanup = await asyncio.to_thread(
                prepare_uat_register_fresh,
                root,
                state=state,
                broker=broker,
            )
            archived = cleanup.get("archived_deployments") or []
            if archived:
                logger.info("UAT register: archived %s before fresh OCR", archived)

            progress = await message.reply_text(
                "⏳ UAT: loading positions (Cursor chat book or Sensibull OCR)…"
            )
            try:
                result = await asyncio.to_thread(ingest_uat_for_register, root)
                if result.get("method") == "cursor_chat":
                    await progress.edit_text(
                        "✅ UAT: using positions from Cursor chat (Sensibull screenshot). "
                        "Continuing register…"
                    )
            except UATIngestError as exc:
                err = str(exc)
                await progress.edit_text(f"UAT: cannot register Batman.\n\n{err}")
                publish_uat_ingest_failure(context.bot_data.get("event_bus"), err)
                _append_log("wizard_cancelled", reason="uat_ingest_failed")
                _clear_wizard_data(context)
                return ConversationHandler.END
            refresh = getattr(broker, "refresh_fixture_positions", None)
            if callable(refresh):
                await asyncio.to_thread(refresh)
            try:
                await progress.delete()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("UAT register ingest skipped: %s", exc)

    _append_log("wizard_started", by="rahul")

    return await _wizard_fetch_step1(context, reply_target=message, prefer_edit=prefer_edit)


async def wizard_entry_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point when Register is tapped from the alive menu button."""
    query = _require_query(update)
    await _safe_answer_callback(query)
    message = query.message
    if message is None:
        return ConversationHandler.END
    context.user_data["_register_prefer_edit"] = True
    return await wizard_entry(Update(update.update_id, message=message), context)


async def wizard_pre_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Yes/Cancel safety check when Batman is already armed."""
    query = _require_query(update)
    await _safe_answer_callback(query)

    if query.data == f"{_CB_PRE}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await _wizard_edit_step(
            context,
            query,
            "✅ Cancelled — existing Batman deployment unchanged\\.",
        )
        return ConversationHandler.END

    # Archive existing and proceed to step 1
    moved = _archive_active_deployments()
    if moved:
        _append_log("archive_moved", files=moved)
        await _wizard_edit_step(
            context,
            query,
            f"📦 Archived previous deployment \\(`{'`, `'.join(moved)}`\\)\\.\n\n"
            "Fetching your NIFTY positions…",
        )
    elif query.message is not None:
        await _wizard_edit_step(context, query, "Fetching your NIFTY positions…")

    return await _wizard_fetch_step1(context, reply_target=query.message, prefer_edit=True)


async def _uat_refresh_book_for_register(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    broker: Any | None = None,
) -> str | None:
    """Reload cursor_chat / OCR book into ShadowBroker before Register leg pick.

    Batman Complete used to call ``_wizard_fetch_step1`` alone — skipping ingest —
    so a newly written Sensibull book (or a repo-local uat/ copy) never replaced
    the in-session \"cache\" PE BUY list.
    """
    from core.batman_mode import is_uat, workspace_root

    if not is_uat():
        return None

    root = workspace_root()
    broker = broker if broker is not None else context.bot_data.get("broker")
    state = context.bot_data.get("state")

    try:
        from core.uat_ingest import UATIngestError, ingest_uat_for_register
        from core.uat_positions import reconcile_uat_positions_books
        from core.uat_register_cleanup import prepare_uat_register_fresh

        reconcile_uat_positions_books(root)
        await asyncio.to_thread(
            prepare_uat_register_fresh,
            root,
            state=state,
            broker=broker,
        )
        result = await asyncio.to_thread(ingest_uat_for_register, root)
        refresh = getattr(broker, "refresh_fixture_positions", None) if broker else None
        if callable(refresh):
            await asyncio.to_thread(refresh)
        method = str((result or {}).get("method") or "positions")
        path = str((result or {}).get("positions_path") or "")
        logger.info(
            "UAT register book refresh — method=%s path=%s",
            method,
            path,
        )
        return None
    except Exception as exc:
        from core.uat_ingest import UATIngestError

        if isinstance(exc, UATIngestError):
            return str(exc)
        logger.warning("UAT register book refresh soft-failed: %s", exc)
        return None


async def _wizard_fetch_step1(
    context: ContextTypes.DEFAULT_TYPE,
    reply_target,
    *,
    prefer_edit: bool = False,
) -> int:
    """Fetch NIFTY positions from broker and start Step 1."""
    broker = context.bot_data.get("broker")

    if not broker:
        await _wizard_show(
            context,
            reply_target,
            "⚠️ No broker connection\\.\n\n"
            "Send a Dhan access token to DRISHTI first, then retry /register\\.",
            prefer_edit=prefer_edit,
        )
        _append_log("wizard_cancelled", reason="no_broker")
        _clear_wizard_data(context)
        return ConversationHandler.END

    try:
        from core.batman_mode import is_uat, workspace_root
        from core.uat_positions import load_positions_fixture, reconcile_uat_positions_books

        if is_uat():
            reconcile_uat_positions_books(workspace_root())
        refresh = getattr(broker, "refresh_fixture_positions", None)
        if callable(refresh):
            await asyncio.to_thread(refresh)
        df = await asyncio.to_thread(broker.get_positions)
        positions = _enrich_positions_list(context, _filter_nifty_positions(df))
        if is_uat():
            try:
                fx = load_positions_fixture(workspace_root())
                pe_buys = sorted(
                    {
                        int(leg["strike"])
                        for leg in (fx.get("legs") or [])
                        if str(leg.get("type", "")).upper() == "PE"
                        and str(leg.get("side", "BUY")).upper() == "BUY"
                    }
                )
                shown = sorted(
                    {
                        int(p.get("strike") or 0)
                        for p in positions
                        if str(p.get("opt_type") or "").upper() == "PE"
                        and str(p.get("direction") or "").upper() == "LONG"
                    }
                )
                from core.uat_positions import positions_json_path as _pos_path

                logger.info(
                    "Register PE BUY candidates — fixture=%s shown=%s path=%s captured=%s",
                    pe_buys,
                    shown,
                    _pos_path(workspace_root()),
                    fx.get("captured_at"),
                )
                if pe_buys and shown and pe_buys != shown:
                    logger.error(
                        "Register ABORT — PE BUY book mismatch fixture=%s shown=%s",
                        pe_buys,
                        shown,
                    )
                    await _wizard_show(
                        context,
                        reply_target,
                        "⚠️ *UAT book mismatch*\n\n"
                        f"Fixture PE BUY: `{_md2_code(', '.join(str(x) for x in pe_buys))}`\n"
                        f"Broker showed: `{_md2_code(', '.join(str(x) for x in shown))}`\n\n"
                        "Stale ShadowBroker / positions\\.json drift\\. "
                        "Re\\-run FAST UAT write, then /register again\\.",
                        prefer_edit=False,
                    )
                    _append_log("wizard_cancelled", reason="uat_pe_buy_mismatch")
                    _clear_wizard_data(context)
                    return ConversationHandler.END
            except Exception as exc:
                logger.warning("Register PE BUY audit soft-failed: %s", exc)
    except Exception as exc:
        logger.error("Wizard Step 1 — broker error: %s", exc)
        await _wizard_show(
            context,
            reply_target,
            f"⚠️ Could not fetch positions from broker: {_md2(exc)}\n\n"
            "Check DRISHTI /health and retry /register\\.",
            prefer_edit=prefer_edit,
        )
        _append_log("wizard_cancelled", reason="broker_error")
        _clear_wizard_data(context)
        return ConversationHandler.END

    if not positions:
        _append_log("wizard_no_positions")
        _clear_wizard_data(context)
        await _wizard_show(
            context,
            reply_target,
            "⚠️ No open NIFTY option positions found in your broker account\\.\n\n"
            "Deploy your Batman iron condor on Dhan first, then run /register\\.",
            prefer_edit=prefer_edit,
        )
        return ConversationHandler.END

    wizard_data = _wizard_data(context)
    wizard_data["wiz_positions"] = positions
    wizard_data["wiz_selected"] = {}
    wizard_data["pe_enabled"] = None
    wizard_data["ce_enabled"] = None
    rebuild_wizard_plan(wizard_data)

    # Skip Enable PE / Enable CE — go straight to leg pick (PE BUY or CE BUY).
    from bat_telegram.bots.kavach2.register_wizard import begin_register_leg_pick

    return await begin_register_leg_pick(
        context, reply_target, prefer_edit=prefer_edit
    )


async def _wizard_handle_leg(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    next_prompt: str,
    next_state: int,
) -> int:
    """Shared handler for Steps 1–3 leg selection callbacks."""
    query = _require_query(update)
    wizard_data = _wizard_data(context)

    if query.data == f"{_CB_LEG}:cancel":
        await _safe_answer_callback(query)
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await _wizard_edit_step(
            context,
            query,
            "❌ Deployment cancelled\\. Run /register when ready\\.",
        )
        return ConversationHandler.END

    all_pos = cast(list[dict[str, Any]], wizard_data["wiz_positions"])
    selected = cast(dict[str, dict[str, Any]], wizard_data["wiz_selected"])
    used = {v["symbol"] for v in selected.values()}
    available = [p for p in all_pos if p["symbol"] not in used]

    data = query.data or ""
    try:
        idx = int(data.split(":")[-1])
    except (ValueError, IndexError):
        await _safe_answer_callback(
            query, "Invalid selection — please tap a button.", show_alert=True
        )
        return next_state - 1

    if idx >= len(available):
        await _safe_answer_callback(
            query, "Invalid selection — please tap a button.", show_alert=True
        )
        return next_state - 1

    answered = await _safe_answer_callback(query)
    if not answered:
        await _wizard_edit_step(
            context,
            query,
            "⏱ That button expired\\. Tap *Register* again to restart the wizard\\.",
        )
        _clear_wizard_data(context)
        return ConversationHandler.END

    selected[role] = available[idx]
    wizard_data["wiz_selected"] = selected

    # Build next keyboard
    new_used = {v["symbol"] for v in selected.values()}
    remaining = [p for p in all_pos if p["symbol"] not in new_used]
    header = _selected_header(selected)
    text = f"{header}\n\n*{_md2(next_prompt)}*"

    await _wizard_edit_step(
        context,
        query,
        text,
        reply_markup=_positions_keyboard(remaining),
    )
    return next_state


async def wizard_step1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _wizard_handle_leg(
        update,
        context,
        "pe_buy",
        f"Step 2/{_WIZARD_STEPS_TOTAL} — Select your PE SELL leg (SHORT PE):",
        WIZARD_STEP2,
    )


async def wizard_step2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Records pe_sell; next = CE BUY (step 3) — LOCKED order: PE BUY→PE SELL→CE BUY→CE SELL
    return await _wizard_handle_leg(
        update,
        context,
        "pe_sell",
        f"Step 3/{_WIZARD_STEPS_TOTAL} — Select your CE BUY leg (LONG CE):",
        WIZARD_STEP3,
    )


async def wizard_step3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Records ce_buy; next = CE SELL (step 4)
    return await _wizard_handle_leg(
        update,
        context,
        "ce_buy",
        f"Step 4/{_WIZARD_STEPS_TOTAL} — Select your CE SELL leg (SHORT CE):",
        WIZARD_STEP4,
    )


async def wizard_step4(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """CE SELL selection — then break-even (future) or CE buffer (Phase 1)."""
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await _safe_answer_callback(query)

    if query.data == f"{_CB_LEG}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await _wizard_edit_step(
            context,
            query,
            "❌ Deployment cancelled\\. Run /register when ready\\.",
        )
        return ConversationHandler.END

    all_pos = cast(list[dict[str, Any]], wizard_data["wiz_positions"])
    selected = cast(dict[str, dict[str, Any]], wizard_data["wiz_selected"])
    used = {v["symbol"] for v in selected.values()}
    available = [p for p in all_pos if p["symbol"] not in used]

    data = query.data or ""
    try:
        idx = int(data.split(":")[-1])
    except (ValueError, IndexError):
        await _safe_answer_callback(
            query, "Invalid selection — please tap a button.", show_alert=True
        )
        return WIZARD_STEP4

    if idx >= len(available):
        await _safe_answer_callback(
            query, "Invalid selection — please tap a button.", show_alert=True
        )
        return WIZARD_STEP4

    selected["ce_sell"] = available[idx]
    wizard_data["wiz_selected"] = selected

    # Phase 1: skip break-even — lightweight path straight to ATO buffers.
    if not _WIZARD_BREAK_EVEN_ENABLED:
        return await _wizard_goto_ce_buffer(query, context, selected)

    # ── FUTURE RELEASE: break-even capture (PE → CE → buffers) ────────────────
    be_suggestions = _calculate_break_even_suggestions(selected)
    wizard_data["wiz_be_suggestions"] = be_suggestions
    wizard_data["wiz_break_even"] = {}
    wizard_data["wiz_break_even_source"] = {}
    wizard_data["wiz_break_even_skipped"] = False

    header = _selected_header(selected)
    await _wizard_edit_step(
        context,
        query,
        f"{header}\n\n{_break_even_prompt_text('pe', (be_suggestions or {}).get('pe'), be_suggestions is None)}",
        reply_markup=_break_even_keyboard("pe", manual_only=be_suggestions is None),
    )
    return WIZARD_BE_PE


# ── FUTURE RELEASE: break-even wizard handlers (disabled in Phase 1) ──────────
async def wizard_be_pe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """PE break-even confirm/edit/skip stage."""
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    data = query.data or ""
    if data.endswith(":cancel"):
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    action = data.split(":")[-1]
    suggestions = cast(dict[str, int] | None, wizard_data.get("wiz_be_suggestions"))
    if action == "confirm" and suggestions is not None:
        cast(dict[str, int], wizard_data["wiz_break_even"])["pe"] = suggestions["pe"]
        cast(dict[str, str], wizard_data["wiz_break_even_source"])["pe"] = "auto"
    elif action == "edit":
        await query.edit_message_text(
            r"✏️ *Enter PE break\-even*\n\nReply with one integer strike that is divisible by 50\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WIZARD_BE_PE_MANUAL
    elif action == "skip":
        wizard_data["wiz_be_skip_from"] = "pe"
        await query.edit_message_text(
            r"⚠️ *Skip break\-even?*\n\n"
            r"Break\-even will not be stored for this deployment\.\n"
            r"RATRIPAL and ADITYA will remain disabled\.\n"
            r"Core KAVACH 2\.0 and ATO flow continues normally\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_break_even_skip_confirm_keyboard(),
        )
        return WIZARD_BE_SKIP_CONFIRM
    else:
        await query.answer("Invalid selection — please tap a button.", show_alert=True)
        return WIZARD_BE_PE

    await query.edit_message_text(
        _break_even_prompt_text("ce", (suggestions or {}).get("ce"), suggestions is None),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_break_even_keyboard("ce", manual_only=suggestions is None),
    )
    return WIZARD_BE_CE


async def wizard_be_pe_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = _require_message(update)
    wizard_data = _wizard_data(context)
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) % 50 != 0:
        await message.reply_text(
            r"⚠️ Invalid break\-even\. Enter one integer multiple of 50, for example `24250`\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WIZARD_BE_PE_MANUAL

    cast(dict[str, int], wizard_data["wiz_break_even"])["pe"] = int(text)
    cast(dict[str, str], wizard_data["wiz_break_even_source"])["pe"] = "manual"
    suggestions = cast(dict[str, int] | None, wizard_data.get("wiz_be_suggestions"))
    await message.reply_text(
        _break_even_prompt_text("ce", (suggestions or {}).get("ce"), suggestions is None),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_break_even_keyboard("ce", manual_only=suggestions is None),
    )
    return WIZARD_BE_CE


async def wizard_be_ce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    data = query.data or ""
    if data.endswith(":cancel"):
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    action = data.split(":")[-1]
    suggestions = cast(dict[str, int] | None, wizard_data.get("wiz_be_suggestions"))
    if action == "confirm" and suggestions is not None:
        cast(dict[str, int], wizard_data["wiz_break_even"])["ce"] = suggestions["ce"]
        cast(dict[str, str], wizard_data["wiz_break_even_source"])["ce"] = "auto"
    elif action == "edit":
        await query.edit_message_text(
            r"✏️ *Enter CE break\-even*\n\nReply with one integer strike that is divisible by 50\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WIZARD_BE_CE_MANUAL
    elif action == "skip":
        wizard_data["wiz_be_skip_from"] = "ce"
        await query.edit_message_text(
            r"⚠️ *Skip break\-even?*\n\n"
            r"Break\-even will not be stored for this deployment\.\n"
            r"RATRIPAL and ADITYA will remain disabled\.\n"
            r"Core KAVACH 2\.0 and ATO flow continues normally\.",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_break_even_skip_confirm_keyboard(),
        )
        return WIZARD_BE_SKIP_CONFIRM
    else:
        await query.answer("Invalid selection — please tap a button.", show_alert=True)
        return WIZARD_BE_CE

    await query.edit_message_text(
        r"*Step 7/13 — CE ATO Trigger Buffer*\n\n"
        r"Enter the CE fire NIFTY level\.\n"
        r"Enter a NIFTY level \(e\.g\. 24160\)\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_buffer_keyboard(),
    )
    return WIZARD_CE_BUFFER


async def wizard_be_ce_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = _require_message(update)
    wizard_data = _wizard_data(context)
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) % 50 != 0:
        await message.reply_text(
            r"⚠️ Invalid break\-even\. Enter one integer multiple of 50, for example `25450`\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return WIZARD_BE_CE_MANUAL

    cast(dict[str, int], wizard_data["wiz_break_even"])["ce"] = int(text)
    cast(dict[str, str], wizard_data["wiz_break_even_source"])["ce"] = "manual"
    await message.reply_text(
        r"*Step 7/13 — CE ATO Trigger Buffer*\n\n"
        r"Enter the CE fire NIFTY level\.\n"
        r"Enter a NIFTY level \(e\.g\. 24160\)\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_buffer_keyboard(),
    )
    return WIZARD_CE_BUFFER


async def wizard_be_skip_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    data = query.data or ""
    if data == f"{_CB_BE}:skip_back":
        side = wizard_data.get("wiz_be_skip_from", "pe")
        suggestions = cast(dict[str, int] | None, wizard_data.get("wiz_be_suggestions"))
        await query.edit_message_text(
            _break_even_prompt_text(side, (suggestions or {}).get(side), suggestions is None),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_break_even_keyboard(side, manual_only=suggestions is None),
        )
        return WIZARD_BE_PE if side == "pe" else WIZARD_BE_CE

    if data != f"{_CB_BE}:skip_confirm":
        await query.answer("Invalid selection — please tap a button.", show_alert=True)
        return WIZARD_BE_SKIP_CONFIRM

    wizard_data["wiz_break_even_skipped"] = True
    wizard_data["wiz_break_even"] = {}
    wizard_data["wiz_break_even_source"] = {}
    await query.edit_message_text(
        r"*Step 7/13 — CE ATO Trigger Buffer*\n\n"
        r"Enter the CE fire NIFTY level\.\n"
        r"Enter a NIFTY level \(e\.g\. 24160\)\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_buffer_keyboard(),
    )
    return WIZARD_CE_BUFFER


async def wizard_ce_buffer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    data = query.data or ""
    if data == f"{_CB_BUF}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    try:
        wizard_data["wiz_ce_entry_buffer_points"] = int(data.split(":")[-1])
    except (ValueError, IndexError):
        await query.answer("Invalid selection — please tap a button.", show_alert=True)
        return WIZARD_CE_BUFFER

    ce_val = cast(int, wizard_data["wiz_ce_entry_buffer_points"])
    await query.edit_message_text(
        rf"*Step 6/{_WIZARD_STEPS_TOTAL} — PE ATO Trigger Buffer*\n\n"
        rf"CE entry selected\n\n"
        r"Choose PE entry buffer or tap the quick option to mirror CE\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_buffer_keyboard(same_value=ce_val),
    )
    return WIZARD_PE_BUFFER


async def wizard_pe_buffer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    data = query.data or ""
    if data == f"{_CB_BUF}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    if data == f"{_CB_BUF}:same":
        wizard_data["wiz_pe_entry_buffer_points"] = wizard_data.get("wiz_ce_entry_buffer_points", 0)
    else:
        try:
            wizard_data["wiz_pe_entry_buffer_points"] = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await query.answer("Invalid selection — please tap a button.", show_alert=True)
            return WIZARD_PE_BUFFER

    await query.edit_message_text(
        rf"*Step 7/{_WIZARD_STEPS_TOTAL} — CE Exit NIFTY Level*\n\n"
        r"Enter the CE retrace NIFTY level used to exit CE ATO after a pullback\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_retrace_keyboard(),
    )
    return WIZARD_CE_RETRACE


async def wizard_ce_retrace(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    if query.data == f"{_CB_RETRACE}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    try:
        ce_retrace_points = int((query.data or "").split(":")[-1])
    except (ValueError, IndexError):
        await query.answer("Invalid selection — please tap a button.", show_alert=True)
        return WIZARD_CE_RETRACE

    wizard_data["wiz_ce_retrace_points"] = ce_retrace_points
    wizard_data["wiz_retrace_points"] = ce_retrace_points
    await query.edit_message_text(
        rf"*Step 8/{_WIZARD_STEPS_TOTAL} — PE Exit NIFTY Level*\n\n"
        rf"CE exit selected\n\n"
        r"Enter the PE retrace NIFTY level used to exit PE ATO after a bounce\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(
            [
                *(_retrace_keyboard().inline_keyboard[:-1]),
                [
                    InlineKeyboardButton(
                        f"Use same as CE ({ce_retrace_points})",
                        callback_data=f"{_CB_RETRACE}:same",
                    )
                ],
                _retrace_keyboard().inline_keyboard[-1],
            ]
        ),
    )
    return WIZARD_PE_RETRACE


async def wizard_pe_retrace(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    data = query.data or ""
    if data == f"{_CB_RETRACE}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    if data == f"{_CB_RETRACE}:same":
        wizard_data["wiz_pe_retrace_points"] = wizard_data.get("wiz_ce_retrace_points", 20)
    else:
        try:
            wizard_data["wiz_pe_retrace_points"] = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await query.answer("Invalid selection — please tap a button.", show_alert=True)
            return WIZARD_PE_RETRACE

    await query.edit_message_text(
        rf"*Step 9/{_WIZARD_STEPS_TOTAL} — ATO Poll Interval*\n\n"
        r"How often should KAVACH check NIFTY LTP for ATO?\n"
        r"This protects against excessive API polling and is selection\-only\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_poll_interval_keyboard(),
    )
    return WIZARD_POLL_INTERVAL


async def wizard_poll_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    data = query.data or ""
    if data == f"{_CB_POLL}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    try:
        poll_interval = int(data.split(":")[-1])
    except (ValueError, IndexError):
        await query.answer("Invalid selection — please tap a button.", show_alert=True)
        return WIZARD_POLL_INTERVAL

    wizard_data["wiz_poll_interval_seconds"] = poll_interval
    _append_log("ato_poll_interval_selected", poll_interval_seconds=poll_interval)

    selected = cast(dict[str, dict[str, Any]], wizard_data["wiz_selected"])
    pe_sell = selected["pe_sell"]
    ce_sell = selected["ce_sell"]
    params = context.bot_data.get("params", {})
    ato_step = params.get("deploy_wizard", {}).get("ato_step", 50)
    pe_ato = pe_sell["strike"] - ato_step
    ce_ato = ce_sell["strike"] + ato_step

    await query.edit_message_text(
        f"✅ Poll interval: *{poll_interval} sec*\n\n"
        f"*Step {_WIZARD_STEPS_TOTAL}/{_WIZARD_STEPS_TOTAL} — ATO Monitoring Mode*\n\n"
        f"Batman's ATO protection strikes:\n"
        f"  \U0001f53b PE ATO: `{pe_ato:,}`\n"
        f"  \U0001f53a CE ATO: `{ce_ato:,}`\n\n"
        f"Which side\\(s\\) should the algo automatically manage?",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_ato_monitor_keyboard(),
    )
    return WIZARD_STEP6


async def wizard_step6(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ATO monitoring side selection — then trading-days review (future) or confirm."""
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    if query.data == f"{_CB_ATO_MON}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    data = query.data or ""
    side = data.split(":")[-1]
    if side not in ("pe", "ce", "both"):
        await query.answer("Invalid selection — please tap a button.", show_alert=True)
        return WIZARD_STEP6

    wizard_data["wiz_ato_manage_sides"] = side
    _append_log("ato_monitor_selected", ato_manage_sides=side)

    # Phase 1: auto-fill calendar defaults and skip holiday review UI.
    if not _WIZARD_TRADING_DAYS_REVIEW_ENABLED:
        _wizard_seed_trading_calendar_defaults(wizard_data)
        return await _wizard_show_summary(query, context)

    # ── FUTURE RELEASE: trading-days / holiday review (Hedge Box calendar) ────
    deploy_date = datetime.now().astimezone().date()
    window = _compute_trade_window(deploy_date)
    wizard_data["wiz_deploy_date"] = window["deploy_date"]
    wizard_data["wiz_expiry_date"] = window["expiry_date"]
    wizard_data["wiz_auto_working_days"] = window["auto_working_days"]
    wizard_data["wiz_extra_holidays"] = []

    text = _render_holiday_review_text(
        deploy_date=window["deploy_date"],
        expiry_date=window["expiry_date"],
        working_days=window["auto_working_days"],
        user_holidays=[],
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_holiday_review_keyboard(window["auto_working_days"], []),
    )
    return WIZARD_STEP7


# ── FUTURE RELEASE: trading-days review handler (disabled in Phase 1) ───────
async def wizard_step7(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Working-day holiday review (Step 13/13) before final summary."""
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    data = query.data or ""
    if data == f"{_CB_HOL}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await query.edit_message_text(
            "❌ Deployment cancelled\\. Run /register when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    working_days = cast(list[date], wizard_data.get("wiz_auto_working_days", []))
    user_holidays = cast(list[date], wizard_data.get("wiz_extra_holidays", []))
    deploy_date = cast(date, wizard_data.get("wiz_deploy_date", datetime.now().astimezone().date()))
    expiry_date = cast(
        date,
        wizard_data.get("wiz_expiry_date", current_week_expiry(expiry_weekday=1, ref=deploy_date)),
    )

    if data == f"{_CB_HOL}:done":
        return await _wizard_show_summary(query, context)

    if data == f"{_CB_HOL}:clear":
        user_holidays = []
    elif data.startswith(f"{_CB_HOL}:toggle:"):
        iso = data.split(":", 2)[-1]
        try:
            picked = date.fromisoformat(iso)
        except ValueError:
            await query.answer("Invalid date selection.", show_alert=True)
            return WIZARD_STEP7

        if picked not in working_days:
            await query.answer("Only listed working days can be marked.", show_alert=True)
            return WIZARD_STEP7

        if picked in user_holidays:
            user_holidays = [d for d in user_holidays if d != picked]
        else:
            user_holidays = sorted([*user_holidays, picked])
    else:
        await query.answer("Invalid selection — please tap a button.", show_alert=True)
        return WIZARD_STEP7

    wizard_data["wiz_extra_holidays"] = user_holidays
    text = _render_holiday_review_text(
        deploy_date=deploy_date,
        expiry_date=expiry_date,
        working_days=working_days,
        user_holidays=user_holidays,
    )
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_holiday_review_keyboard(working_days, user_holidays),
    )
    return WIZARD_STEP7


def _full_selected_from_wizard(wizard_data: dict[str, Any]) -> dict[str, dict | None]:
    """Build deployment positions map with null legs for skipped sides."""
    out: dict[str, dict | None] = {
        "pe_buy": None,
        "pe_margin_hedge": None,
        "pe_dyn_hedge": None,
        "pe_sell": None,
        "ce_buy": None,
        "ce_margin_hedge": None,
        "ce_dyn_hedge": None,
        "ce_sell": None,
    }
    if wizard_data.get("pe_enabled"):
        out["pe_buy"] = wizard_data.get("pe_buy")
        out["pe_margin_hedge"] = wizard_data.get("pe_margin_hedge")
        out["pe_dyn_hedge"] = wizard_data.get("pe_dyn_hedge")
        out["pe_sell"] = wizard_data.get("pe_sell")
    if wizard_data.get("ce_enabled"):
        out["ce_buy"] = wizard_data.get("ce_buy")
        out["ce_margin_hedge"] = wizard_data.get("ce_margin_hedge")
        out["ce_dyn_hedge"] = wizard_data.get("ce_dyn_hedge")
        out["ce_sell"] = wizard_data.get("ce_sell")
    return out


async def _recheck_broker_at_confirm(
    context: ContextTypes.DEFAULT_TYPE, wizard_data: dict[str, Any]
) -> tuple[bool, str]:
    """Re-verify broker still holds registered legs at confirm (H2)."""
    broker = context.bot_data.get("broker")
    if not broker:
        return False, "No broker connection."
    try:
        df = await asyncio.to_thread(broker.get_positions)
        live = _filter_nifty_positions(df)
    except Exception as exc:
        return False, f"Could not fetch broker positions: {exc}"
    sym_qty = {p["symbol"]: abs(int(p["qty"])) for p in live}
    for role in ("pe_buy", "pe_sell", "ce_buy", "ce_sell"):
        leg = wizard_data.get(role)
        if not leg:
            continue
        sym = leg["symbol"]
        managed = abs(int(leg.get("qty", 0)))
        broker_qty = sym_qty.get(sym, 0)
        if broker_qty < managed:
            return (
                False,
                f"{sym}: broker has {broker_qty} qty but registration needs {managed}. "
                "Re-run /register.",
            )
    return True, ""


async def _wizard_show_summary(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display deployment summary for final confirmation."""
    wizard_data = _wizard_data(context)
    selected = _full_selected_from_wizard(wizard_data)
    wizard_data["wiz_selected"] = {k: v for k, v in selected.items() if v}
    params = context.bot_data.get("params", {})
    ato_step = params.get("deploy_wizard", {}).get("ato_step", 50)
    ce_entry_raw = wizard_data.get(
        "wiz_ce_entry_buffer", wizard_data.get("wiz_ce_entry_buffer_points", 0)
    )
    pe_entry_raw = wizard_data.get(
        "wiz_pe_entry_buffer", wizard_data.get("wiz_pe_entry_buffer_points", 0)
    )
    ce_exit_raw = wizard_data.get("wiz_ce_exit_buffer", wizard_data.get("wiz_ce_retrace_points", 5))
    pe_exit_raw = wizard_data.get("wiz_pe_exit_buffer", wizard_data.get("wiz_pe_retrace_points", 5))
    poll_interval_seconds = cast(int | None, wizard_data.get("wiz_poll_interval_seconds"))
    ato_manage_sides = cast(str, wizard_data.get("wiz_ato_manage_sides", "both"))
    lot_size = int((params.get("strategy") or {}).get("lot_size", 65))
    scope = build_registration_scope(
        pe_enabled=bool(wizard_data.get("pe_enabled")),
        ce_enabled=bool(wizard_data.get("ce_enabled")),
        pe_managed_lots=wizard_data.get("pe_managed_lots"),
        ce_managed_lots=wizard_data.get("ce_managed_lots"),
        pe_ato_lots=wizard_data.get("pe_ato_lots"),
        ce_ato_lots=wizard_data.get("ce_ato_lots"),
        lot_size=lot_size,
    )
    wizard_data["wiz_registration_scope"] = scope
    sides_label = {
        "pe": "PE side only \U0001f53b",
        "ce": "CE side only \U0001f53a",
        "both": "Both sides \u26a1 \\(recommended\\)",
    }
    levels = _side_levels(selected, wizard_data)
    wizard_data["wiz_ato_step"] = ato_step

    def _fmt_leg(leg: dict | None) -> str:
        if not leg:
            return _md2("— skipped —")
        return _md2_code(f"{leg.get('symbol')} qty={leg.get('qty')} avg=₹{leg.get('avg_price')}")

    summary = ""
    plan = wizard_data.get("wiz_plan") or rebuild_wizard_plan(wizard_data)
    cidx, ctotal = question_index(plan, "confirm")
    summary += (
        f"*Question {cidx} of {ctotal} — Confirm deployment*\n\n"
        "🦇 *Batman Position Summary*\n\n"
    )
    if wizard_data.get("pe_enabled"):
        pe_sell = selected["pe_sell"]
        pe_ato_strike = int(
            wizard_data.get("pe_protect_strike")
            or auto_protect_strike(int(pe_sell["strike"]), "PE", ato_step=int(ato_step))
        )
        pe_ato_sym = str(
            wizard_data.get("pe_protect_symbol")
            or build_ato_protect_symbol(pe_sell["symbol"], pe_ato_strike, "PE")
        )
        summary += (
            f"`PE BUY  : {_fmt_leg(selected['pe_buy'])}`\n"
            f"`PE SELL : {_fmt_leg(pe_sell)}`\n"
        )
        if selected.get("pe_margin_hedge"):
            summary += f"`PE MARGIN: {_fmt_leg(selected['pe_margin_hedge'])}`\n"
        if selected.get("pe_dyn_hedge"):
            summary += f"`PE 30%DYN: {_fmt_leg(selected['pe_dyn_hedge'])}`\n"
        summary += f"ATO PE: `{_md2_code(pe_ato_sym)}`\n\n"
    else:
        summary += f"`{_md2_code('PE side: not registered')}`\n\n"

    if wizard_data.get("ce_enabled"):
        ce_sell = selected["ce_sell"]
        ce_ato_strike = int(
            wizard_data.get("ce_protect_strike")
            or auto_protect_strike(int(ce_sell["strike"]), "CE", ato_step=int(ato_step))
        )
        ce_ato_sym = str(
            wizard_data.get("ce_protect_symbol")
            or build_ato_protect_symbol(ce_sell["symbol"], ce_ato_strike, "CE")
        )
        summary += (
            f"`CE BUY  : {_fmt_leg(selected['ce_buy'])}`\n"
            f"`CE SELL : {_fmt_leg(ce_sell)}`\n"
        )
        if selected.get("ce_margin_hedge"):
            summary += f"`CE MARGIN: {_fmt_leg(selected['ce_margin_hedge'])}`\n"
        if selected.get("ce_dyn_hedge"):
            summary += f"`CE 30%DYN: {_fmt_leg(selected['ce_dyn_hedge'])}`\n"
        summary += f"ATO CE: `{_md2_code(ce_ato_sym)}`\n\n"
    else:
        summary += f"`{_md2_code('CE side: not registered')}`\n\n"

    summary += f"{_md2('ATO NIFTY levels:')}\n"
    if wizard_data.get("ce_enabled") and "ce_trigger" in levels:
        summary += (
            f"`CE fire    : {_md2_code(f'{levels['ce_trigger']:,}')}`\n"
            f"`CE retrace : {_md2_code(f'{levels['ce_retrace']:,}')}`\n"
        )
    if wizard_data.get("pe_enabled") and "pe_trigger" in levels:
        summary += (
            f"`PE fire    : {_md2_code(f'{levels['pe_trigger']:,}')}`\n"
            f"`PE retrace : {_md2_code(f'{levels['pe_retrace']:,}')}`\n"
        )
    poll_label = _md2(str(poll_interval_seconds or "config default"))
    summary += (
        f"\nPoll interval: *{poll_label} sec*\n\n"
        f"🤖 ATO monitoring: *{sides_label.get(ato_manage_sides, _md2(ato_manage_sides))}*"
    )
    warnings = _ato_lots_warning_lines(wizard_data, selected, lot_size)
    warnings.extend(_protect_strike_warning_lines(wizard_data, selected))
    warnings.extend(_orphan_leg_warning_lines(context, wizard_data, selected))
    if warnings:
        summary += "\n\n" + "\n".join(warnings)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm & Arm Batman", callback_data=f"{_CB_CONF}:confirm"
                ),
                InlineKeyboardButton("❌ Cancel & Start Over", callback_data=f"{_CB_CONF}:cancel"),
            ]
        ]
    )
    await _edit_md2(query, summary, reply_markup=keyboard)
    return WIZARD_CONFIRM


async def wizard_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the final Confirm / Cancel choice."""
    query = _require_query(update)
    wizard_data = _wizard_data(context)
    await query.answer()

    if query.data == f"{_CB_CONF}:cancel":
        _append_log("wizard_cancelled")
        _clear_wizard_data(context)
        await _edit_md2(
            query,
            "❌ Deployment cancelled\\. No file written\\.\n\nRun /register again when ready\\.",
        )
        return ConversationHandler.END

    ok, err = await _recheck_broker_at_confirm(context, wizard_data)
    if not ok:
        await query.edit_message_text(
            f"⚠️ Broker check failed: {_md2(err)}\n\nRun /register again\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        _append_log("wizard_cancelled", reason="broker_recheck_failed")
        _clear_wizard_data(context)
        return ConversationHandler.END

    selected = _full_selected_from_wizard(wizard_data)
    ato_step = cast(int, wizard_data.get("wiz_ato_step", 50))
    ce_entry_raw = wizard_data.get(
        "wiz_ce_entry_buffer", wizard_data.get("wiz_ce_entry_buffer_points", 0)
    )
    pe_entry_raw = wizard_data.get(
        "wiz_pe_entry_buffer", wizard_data.get("wiz_pe_entry_buffer_points", 0)
    )
    ce_exit_raw = wizard_data.get("wiz_ce_exit_buffer", wizard_data.get("wiz_ce_retrace_points", 5))
    pe_exit_raw = wizard_data.get("wiz_pe_exit_buffer", wizard_data.get("wiz_pe_retrace_points", 5))
    poll_interval_seconds = cast(int | None, wizard_data.get("wiz_poll_interval_seconds"))
    break_even = cast(dict[str, int], wizard_data.get("wiz_break_even", {}))
    break_even_skipped = bool(wizard_data.get("wiz_break_even_skipped", False))
    ato_manage_sides = cast(str, wizard_data.get("wiz_ato_manage_sides", "both"))
    if not wizard_data.get("wiz_deploy_date"):
        _wizard_seed_trading_calendar_defaults(wizard_data)
    deploy_date = cast(date | None, wizard_data.get("wiz_deploy_date"))
    expiry_date = cast(date | None, wizard_data.get("wiz_expiry_date"))
    auto_working_days = cast(list[date], wizard_data.get("wiz_auto_working_days", []))
    extra_holidays = cast(list[date], wizard_data.get("wiz_extra_holidays", []))
    effective_working_days: list[date] = [
        d for d in auto_working_days if d not in set(extra_holidays)
    ]
    scope = cast(dict[str, Any], wizard_data.get("wiz_registration_scope"))
    if not scope:
        scope = build_registration_scope(
            pe_enabled=bool(wizard_data.get("pe_enabled")),
            ce_enabled=bool(wizard_data.get("ce_enabled")),
            pe_managed_lots=wizard_data.get("pe_managed_lots"),
            ce_managed_lots=wizard_data.get("ce_managed_lots"),
            pe_ato_lots=wizard_data.get("pe_ato_lots"),
            ce_ato_lots=wizard_data.get("ce_ato_lots"),
            lot_size=int(
                (context.bot_data.get("params", {}).get("strategy") or {}).get("lot_size", 65)
            ),
        )

    strike_errors = _validate_protect_strikes_at_confirm(wizard_data, selected)
    if strike_errors:
        err_text = "\n".join(f"• {_md2(e)}" for e in strike_errors)
        await _edit_md2(
            query,
            f"❌ *Cannot confirm*\n\n{err_text}\n\nFix strike selection and try again\\.",
        )
        return WIZARD_CONFIRM

    profile = _economy_profile_flags(wizard_data, scope)

    trading_calendar = {
        "deploy_date": deploy_date.isoformat() if deploy_date else None,
        "expiry_date": expiry_date.isoformat() if expiry_date else None,
        "auto_working_days": [d.isoformat() for d in auto_working_days],
        "user_marked_holidays": [d.isoformat() for d in extra_holidays],
        "effective_working_days": [d.isoformat() for d in effective_working_days],
    }

    try:
        filepath = _write_deployment_file(
            selected,
            scope,
            ato_step=ato_step,
            ce_entry_buffer=ce_entry_raw if wizard_data.get("ce_enabled") else 0,
            pe_entry_buffer=pe_entry_raw if wizard_data.get("pe_enabled") else 0,
            ce_retrace_buffer=ce_exit_raw if wizard_data.get("ce_enabled") else 5,
            pe_retrace_buffer=pe_exit_raw if wizard_data.get("pe_enabled") else 5,
            poll_interval_seconds=poll_interval_seconds,
            ato_manage_sides=ato_manage_sides,
            pe_protect_strike=wizard_data.get("pe_protect_strike"),
            pe_protect_symbol=wizard_data.get("pe_protect_symbol"),
            pe_protect_strike_mode=wizard_data.get("pe_protect_strike_mode"),
            ce_protect_strike=wizard_data.get("ce_protect_strike"),
            ce_protect_symbol=wizard_data.get("ce_protect_symbol"),
            ce_protect_strike_mode=wizard_data.get("ce_protect_strike_mode"),
            break_even={
                "pe": break_even.get("pe"),
                "ce": break_even.get("ce"),
                "skipped": break_even_skipped,
            },
            trading_calendar=trading_calendar,
            profile=profile,
            order_mode=str(wizard_data.get("order_mode") or "paper"),
        )
    except Exception as exc:
        logger.error("Failed to write deployment file: %s", exc)
        await query.edit_message_text(f"⚠️ Failed to write deployment file: {exc}")
        _append_log("wizard_cancelled", reason="file_write_error")
        _clear_wizard_data(context)
        return ConversationHandler.END

    try:
        await asyncio.to_thread(
            _finalize_register_confirm,
            context,
            filepath,
            wizard_data,
            selected,
            poll_interval_seconds,
            ato_manage_sides,
        )
    except DeploymentLockBusy as exc:
        await _edit_md2(
            query,
            f"⚠️ Deployment busy — try again in a moment\\.\n\n`{_md2_code(str(exc))}`",
        )
        return ConversationHandler.END

    levels = _side_levels(selected, wizard_data)

    confirm_lines = [
        "✅ *Batman armed\\. KAVACH is watching\\.*",
        "",
        f"File: `{_md2_code(filepath.name)}`",
    ]
    if wizard_data.get("ce_enabled"):
        confirm_lines.append(
            f"CE levels: fire *{_md2(str(levels.get('ce_trigger', '—')))}* / "
            f"retrace *{_md2(str(levels.get('ce_retrace', '—')))}*"
        )
    if wizard_data.get("pe_enabled"):
        confirm_lines.append(
            f"PE levels: fire *{_md2(str(levels.get('pe_trigger', '—')))}* / "
            f"retrace *{_md2(str(levels.get('pe_retrace', '—')))}*"
        )
    poll_label = _md2(str(poll_interval_seconds or "config default"))
    confirm_lines.extend(
        [
            f"Poll interval: *{poll_label} sec*",
            "",
            "Algo state: *Enabled* ✅",
            f"ATO monitoring: *{_md2(ato_manage_sides.upper())}*",
        ]
    )
    if wizard_data.get("pe_enabled") and "pe_trigger" in levels:
        confirm_lines.append(f"PE ATO fires when NIFTY ≤ {_md2(f'{levels['pe_trigger']:,}')}")
    if wizard_data.get("ce_enabled") and "ce_trigger" in levels:
        confirm_lines.append(f"CE ATO fires when NIFTY ≥ {_md2(f'{levels['ce_trigger']:,}')}")

    await _edit_md2(query, "\n".join(confirm_lines))
    if query.message is not None:
        await _send_alive_menu(query.message)
    _clear_wizard_data(context)
    return ConversationHandler.END


async def wizard_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Called when wizard idles longer than wizard_timeout_seconds."""
    _append_log("wizard_timeout")
    _clear_wizard_data(context)
    if update.effective_message:
        await update.effective_message.reply_text(
            "⏱ Wizard timed out\\. No file written\\.\n\nRun /register again when ready\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
# Command handlers — non-wizard
# ═══════════════════════════════════════════════════════════════════════════════


async def cmd_environment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core.environment_display import environment_short_message

    message = _require_message(update)
    await message.reply_text(
        environment_short_message(),
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await _send_alive_menu(message)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await _send_alive_menu(message)


async def cmd_ato_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    dep_file = _find_active_deployment()
    if not dep_file:
        await _reply_md2(
            message,
            "⚠️ No active deployment\\.\n\nTap *Register* to arm Batman\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return

    state = context.bot_data.get("state")
    ce_trig = state.get("ato.ce_ato_active", False) if state else False
    pe_trig = state.get("ato.pe_ato_active", False) if state else False
    if state and not ce_trig:
        ce_trig = bool(state.get("ato.ce_triggered", False))
    if state and not pe_trig:
        pe_trig = bool(state.get("ato.pe_triggered", False))
    ce_sym = state.get("ato.ce_protect_symbol", "N/A") if state else "N/A"
    pe_sym = state.get("ato.pe_protect_symbol", "N/A") if state else "N/A"
    ce_entry_buffer = state.get("ato.ce_entry_buffer_points", 0) if state else 0
    pe_entry_buffer = state.get("ato.pe_entry_buffer_points", 0) if state else 0
    ce_retrace_points = (
        state.get("ato.ce_retrace_points", state.get("ato.retrace_points", 5)) if state else 5
    )
    pe_retrace_points = (
        state.get("ato.pe_retrace_points", state.get("ato.retrace_points", 5)) if state else 5
    )
    poll_interval = state.get("ato.poll_interval_seconds") if state else None
    managed = state.get("ato.manage_sides", "both") if state else "both"
    ce_sell_strike: int | None = None
    pe_sell_strike: int | None = None
    try:
        with open(dep_file, encoding="utf-8") as fh:
            dep = json.load(fh)
        positions = dep.get("positions") if isinstance(dep, dict) else {}
        ato_block = dep.get("ato") if isinstance(dep, dict) else {}
        if not isinstance(ato_block, dict):
            ato_block = {}
        ce_sell_strike = _leg_strike(positions if isinstance(positions, dict) else {}, "ce_sell")
        pe_sell_strike = _leg_strike(positions if isinstance(positions, dict) else {}, "pe_sell")
        # Prefer deployment buffers when state is empty / not yet synced.
        if state is not None:
            ce_entry_buffer = state.get(
                "ato.ce_entry_buffer_points",
                ato_block.get("ce_entry_buffer_points", ce_entry_buffer),
            )
            pe_entry_buffer = state.get(
                "ato.pe_entry_buffer_points",
                ato_block.get("pe_entry_buffer_points", pe_entry_buffer),
            )
            ce_retrace_points = state.get(
                "ato.ce_retrace_points",
                ato_block.get("ce_retrace_points", ce_retrace_points),
            )
            pe_retrace_points = state.get(
                "ato.pe_retrace_points",
                ato_block.get("pe_retrace_points", pe_retrace_points),
            )
            if poll_interval is None:
                poll_interval = ato_block.get("poll_interval_seconds")
            if managed in (None, "", "both") and ato_block.get("manage_sides"):
                managed = ato_block.get("manage_sides", managed)
        else:
            ce_entry_buffer = ato_block.get("ce_entry_buffer_points", ce_entry_buffer)
            pe_entry_buffer = ato_block.get("pe_entry_buffer_points", pe_entry_buffer)
            ce_retrace_points = ato_block.get("ce_retrace_points", ce_retrace_points)
            pe_retrace_points = ato_block.get("pe_retrace_points", pe_retrace_points)
            poll_interval = ato_block.get("poll_interval_seconds", poll_interval)
        # Protect-strike fallback when sell leg missing.
        if pe_sell_strike is None:
            pe_sell_strike = _coerce_strike(ato_block.get("pe_protect_strike"))
        if ce_sell_strike is None:
            ce_sell_strike = _coerce_strike(ato_block.get("ce_protect_strike"))
        if not ce_sym or ce_sym in ("N/A", "None", None):
            ce_sym = ato_block.get("ce_protect_symbol") or "None"
        if not pe_sym or pe_sym in ("N/A", "None", None):
            pe_sym = ato_block.get("pe_protect_symbol") or "None"
        if poll_interval is None and isinstance(dep, dict):
            poll_interval = dep.get("ato", {}).get("poll_interval_seconds") if isinstance(dep.get("ato"), dict) else None
    except Exception as exc:
        logger.warning("ATO status deployment parse failed: %s", exc)

    sides_label = {
        "pe": "PE side only \U0001f53b",
        "ce": "CE side only \U0001f53a",
        "both": "Both sides \u26a1",
    }

    def _fmt_level(v: int | None) -> str:
        return f"{v:,}" if isinstance(v, int) else "—"

    ce_entry = _buffer_points(ce_entry_buffer, 0)
    pe_entry = _buffer_points(pe_entry_buffer, 0)
    ce_exit_pts = _buffer_points(ce_retrace_points, 5)
    pe_exit_pts = _buffer_points(pe_retrace_points, 5)

    from core.buffer_config.levels import ato_absolute_levels

    levels = ato_absolute_levels(
        pe_sell_strike=pe_sell_strike,
        ce_sell_strike=ce_sell_strike,
        pe_entry_buffer=pe_entry,
        ce_entry_buffer=ce_entry,
        pe_exit_buffer=pe_exit_pts,
        ce_exit_buffer=ce_exit_pts,
    )
    pe_trigger_level = levels["pe_trigger"]
    ce_trigger_level = levels["ce_trigger"]
    pe_exit_level = levels["pe_exit"]
    ce_exit_level = levels["ce_exit"]

    poll_label = _md2(str(poll_interval if poll_interval is not None else "config default"))
    from core.ato_monitoring_schedule import format_monitoring_schedule_line
    from bat_telegram.bots.kavach2.ato_configuration_wizard import _CB_ATC

    schedule_line = _md2(format_monitoring_schedule_line(deployed=True))
    status_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Buffer Manager", callback_data=f"{_CB_ATC}:start"
                )
            ],
            [InlineKeyboardButton("« Main menu", callback_data=f"{_CB_MENU}:main")],
        ]
    )
    ce_sym_disp = "None" if ce_sym in (None, "N/A", "None", "") else str(ce_sym)
    pe_sym_disp = "None" if pe_sym in (None, "N/A", "None", "") else str(pe_sym)
    await _reply_md2(
        message,
        f"🛡 *ATO Status*\n\n"
        f"Schedule   : {schedule_line}\n\n"
        f"CE side : {'🔴 TRIGGERED' if ce_trig else '🟢 IDLE'}\n"
        f"  Symbol : `{_md2_code(ce_sym_disp)}`\n"
        f"  Fires ≥: `{_md2_code(_fmt_level(ce_trigger_level))}`\n"
        f"  Retrace exit ≤: `{_md2_code(_fmt_level(ce_exit_level))}`\n\n"
        f"PE side : {'🔴 TRIGGERED' if pe_trig else '🟢 IDLE'}\n"
        f"  Symbol : `{_md2_code(pe_sym_disp)}`\n"
        f"  Fires ≤: `{_md2_code(_fmt_level(pe_trigger_level))}`\n"
        f"  Retrace exit ≥: `{_md2_code(_fmt_level(pe_exit_level))}`\n\n"
        f"⏱ Poll interval: *{poll_label} sec*\n"
        f"🤖 Algo manages: *{_md2(sides_label.get(str(managed), str(managed)))}*",
        reply_markup=status_markup,
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_paused_command(
        update,
        context,
        bot_name="kavach2",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return
    message = _require_message(update)
    if not _find_active_deployment():
        await _reply_md2(
            message,
            "⚠️ No deployment registered\\. Tap *Register* first\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return
    state = context.bot_data.get("state")
    if state:
        state.set("algo.paused", True)
        state.set("algo.pause_reason", "kavach2_manual")
        state.set("algo.paused_by", "kavach2")
    bus = context.bot_data.get("event_bus")
    if bus:
        from core.event_bus import Event

        bus.publish(Event.MODULE_STOPPED, {"module": "ato_protection", "by": "kavach_pause"})
    await _reply_md2(
        message,
        "⏸ *Algo paused\\.*\n\nATO monitoring suspended\\.\nTap *Resume* to restart\\.",
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_resume_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resume visible but blocked — waiting for feed (callback alert)."""
    from core.feed_recovery import LABEL_MANUAL_HANDLING, LABEL_WAITING_FOR_FEED

    query = update.callback_query
    if query is not None:
        await query.answer(
            f"{LABEL_WAITING_FOR_FEED}. DRISHTI is retrying. "
            f"Wait for feed-ready message or tap {LABEL_MANUAL_HANDLING}.",
            show_alert=True,
        )
        return
    message = _require_message(update)
    await message.reply_text(
        f"⛔ <b>{LABEL_WAITING_FOR_FEED}</b> — NIFTY cache is not ready.\n\n"
        "DRISHTI is retrying WebSocket ↔ REST. "
        "KAVACH will refresh this menu when the feed is back.",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


def _recovery_auto_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes, auto resume",
                    callback_data=f"{_CB_MENU}:recovery_auto_confirm",
                ),
                InlineKeyboardButton("Cancel", callback_data=f"{_CB_MENU}:main"),
            ],
        ]
    )


async def cmd_recovery_operator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core.feed_recovery import LABEL_MANUAL_HANDLING, OWNER_OPERATOR, set_recovery_owner

    set_recovery_owner(OWNER_OPERATOR, by="kavach_button")
    message = _require_message(update)
    await message.reply_text(
        f"🙋 <b>{LABEL_MANUAL_HANDLING}</b> — you are in control\n\n"
        "DRISHTI keeps retrying the NIFTY feed in the background.\n"
        "DRISHTI will message you when the feed is back.\n"
        "JAGRAN feed alerts are downgraded to <b>warning</b> while you handle this.\n\n"
        "Then tap <b>Resume</b> here when you want KAVACH to monitor positions.",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_recovery_auto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core.feed_recovery import LABEL_AUTO_RESUME

    message = _require_message(update)
    await message.reply_text(
        f"🤖 Switch to <b>{LABEL_AUTO_RESUME}</b>?\n\n"
        "DRISHTI will auto-resume ATO when the NIFTY cache is fresh.\n"
        "<i>Only confirm if you are not mid-fix on token or VPS.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=_recovery_auto_confirm_keyboard(),
    )


async def cmd_recovery_auto_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core.feed_recovery import LABEL_AUTO_RESUME, OWNER_DRISHTI, set_recovery_owner

    set_recovery_owner(OWNER_DRISHTI, by="kavach_button")
    message = _require_message(update)
    await message.reply_text(
        f"🤖 <b>{LABEL_AUTO_RESUME}</b> enabled\n\n"
        "DRISHTI will auto-resume ATO when the NIFTY cache is fresh and healthy.",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_paused_command(
        update,
        context,
        bot_name="kavach2",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return
    message = _require_message(update)
    if not _find_active_deployment():
        await _reply_md2(
            message,
            "⚠️ No deployment\\. Tap *Register* first\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return

    from core.feed_recovery import evaluate_kavach_resume

    state = context.bot_data.get("state")
    pause_reason = state.get("algo.pause_reason") if state else None
    allowed, note = evaluate_kavach_resume(pause_reason)
    if not allowed:
        await message.reply_text(
        note,
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )
        return

    if state:
        from core.ato_side_state import clear_resumable_side_halts

        state.set("algo.paused", False)
        state.set("algo.pause_reason", None)
        state.set("algo.paused_at", None)
        state.set("algo.paused_by", None)
        cleared = clear_resumable_side_halts(state)
        if cleared:
            state.set("ato.resume_reevaluate", True)
            logger.info("KAVACH resume: cleared side halt(s) %s", cleared)
    bus = context.bot_data.get("event_bus")
    if bus:
        from core.event_bus import Event

        bus.publish(Event.MODULE_STARTED, {"module": "ato_protection", "by": "kavach_resume"})
    from core.feed_recovery import is_nifty_cache_trading_ready

    ready, _ = is_nifty_cache_trading_ready()
    if ready:
        await _reply_md2(
            message,
            "▶ *Algo resumed\\.*\n\nKAVACH is back — monitoring positions with a fresh NIFTY feed\\.",
            reply_markup=_main_menu_keyboard(),
        )
    else:
        await _reply_md2(
            message,
            "▶ *Algo resumed\\.*\n\nATO monitoring is active\\.",
            reply_markup=_main_menu_keyboard(),
        )
    if note:
        await message.reply_text(
        f"⚠️ {note}",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_start_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_paused_command(
        update,
        context,
        bot_name="kavach2",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return
    message = _require_message(update)
    if not _find_active_deployment():
        await _reply_md2(
            message,
            "⚠️ No deployment\\. Tap *Register* first\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return
    state = context.bot_data.get("state")
    if state:
        state.set("algo.paused", False)
        state.set("algo.pause_reason", None)
        state.set("algo.paused_at", None)
        state.set("algo.paused_by", None)
        state.set("deployment.confirmed", True)
    bus = context.bot_data.get("event_bus")
    if bus:
        from core.event_bus import Event

        bus.publish(Event.MODULE_STARTED, {"module": "algo", "by": "kavach_force"})
    await _reply_md2(
        message,
        "▶ *Algo started immediately\\!*\n\nATO monitoring is now active\\.",
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_legs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    dep_file = _find_active_deployment()
    if not dep_file:
        await _reply_md2(
            message,
            "⚠️ No active deployment\\. Tap *Register* first\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return
    try:
        with open(dep_file, encoding="utf-8") as fh:
            dep = json.load(fh)
    except Exception as exc:
        await _reply_md2(
            message,
            f"⚠️ Could not read deployment file: {_md2(exc)}",
            reply_markup=_main_menu_keyboard(),
        )
        return

    p = dep.get("positions", {})
    order = [
        ("pe_buy", "PE BUY "),
        ("pe_margin_hedge", "PE MARGIN"),
        ("pe_dyn_hedge", "PE 30%DYN"),
        ("pe_sell", "PE SELL"),
        ("ce_buy", "CE BUY "),
        ("ce_margin_hedge", "CE MARGIN"),
        ("ce_dyn_hedge", "CE 30%DYN"),
        ("ce_sell", "CE SELL"),
    ]
    lines = ["🦇 *Core Batman Legs*\n"]
    for key, label in order:
        leg = p.get(key, {})
        if leg:
            sym = leg.get("symbol", "?")
            qty = leg.get("qty", "?")
            avg = leg.get("avg_price", "?")
            lines.append(f"`{_md2_code(f'{label}: {sym}  qty={qty}  avg=₹{avg}')}`")

    await _reply_md2(
        message,
        "\n".join(lines),
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show open ATO protect-leg positions only (not full Batman book)."""
    message = _require_message(update)
    broker = context.bot_data.get("broker")
    if not broker:
        await _reply_md2(
            message,
            "⚠️ No broker connection\\. Send token to DRISHTI first\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return

    state = context.bot_data.get("state")
    protect = _collect_ato_protect_symbols(state)
    if not protect:
        await _reply_md2(
            message,
            "📊 *ATO Positions*\n\n"
            "No ATO protect legs registered\\.\n"
            "Tap *Register Batman* to arm protect symbols\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return

    try:
        df = await asyncio.to_thread(broker.get_positions)
        positions = _enrich_positions_list(context, _filter_nifty_positions(df))
    except Exception as exc:
        await _reply_md2(
            message,
            f"⚠️ Could not fetch positions: {_md2(exc)}",
            reply_markup=_main_menu_keyboard(),
        )
        return

    ato_rows = _filter_ato_protect_positions(positions, protect)
    lines = ["📊 *ATO Positions*", ""]
    if not ato_rows:
        lines.append("No open ATO protect legs at broker\\.")
        lines.append("")
        for sym, meta in protect.items():
            side = meta.get("side", "?")
            trig = "triggered" if meta.get("triggered") else "armed"
            lines.append(f"`{_md2_code(f'{side} {sym} — {trig}, qty=0')}`")
    else:
        covered_sides: set[str] = set()
        for pos, meta in ato_rows:
            sym = pos.get("display_symbol") or pos["symbol"]
            px = _format_position_price(pos)
            side = str(meta.get("side", "ATO"))
            covered_sides.add(side)
            trig = " TRIGGERED" if meta.get("triggered") else ""
            plain = f"{side}{trig} | {sym} | {pos['direction']} {pos['qty']} @ {px}"
            lines.append(f"`{_md2_code(plain)}`")
        for sym, meta in protect.items():
            side = str(meta.get("side", "?"))
            if side in covered_sides:
                continue
            trig = "triggered" if meta.get("triggered") else "armed"
            lines.append(f"`{_md2_code(f'{side} {sym} — {trig}, qty=0')}`")

    await _reply_md2(
        message,
        "\n".join(lines),
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_funds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    broker = context.bot_data.get("broker")
    if not broker:
        await _reply_md2(
            message,
            "⚠️ No broker connection\\. Send token to DRISHTI first\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return
    try:
        balance = await asyncio.to_thread(broker.get_balance)
        await _reply_md2(
            message,
            f"💰 *Available Margin*\n\n`{_md2_code(f'Free : ₹{balance:,.2f}')}`",
            reply_markup=_main_menu_keyboard(),
        )
    except Exception as exc:
        await _reply_md2(
            message,
            f"⚠️ Could not fetch balance: {_md2(exc)}",
            reply_markup=_main_menu_keyboard(),
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    dep_file = _find_active_deployment()
    broker = context.bot_data.get("broker")
    state = context.bot_data.get("state")
    ce_trig = state.get("ato.ce_triggered", False) if state else False
    pe_trig = state.get("ato.pe_triggered", False) if state else False
    paused = state.get("algo.paused", False) if state else False
    pause_reason = state.get("algo.pause_reason") if state else None

    broker_line = "✅ Connected" if broker else "🔴 No broker"
    dep_line = f"✅ Armed `{_md2_code(dep_file.name)}`" if dep_file else "⏳ Not deployed"
    from core.ato_monitoring_schedule import (
        format_monitoring_schedule_line,
        is_waiting_for_monitoring_start,
        monitoring_start_hhmm,
    )
    from core.feed_recovery import format_nifty_feed_status_line

    if paused:
        algo_line = "⏸ Paused"
        if pause_reason:
            algo_line = f"⏸ Paused \\({_md2(str(pause_reason))}\\)"
    elif dep_file and is_waiting_for_monitoring_start(deployed=True):
        algo_line = f"⏳ Waiting for {_md2(monitoring_start_hhmm())} IST"
    elif dep_file:
        algo_line = "▶ Running"
    else:
        algo_line = "⏳ Idle"

    nifty_line = _md2(format_nifty_feed_status_line())
    schedule_line = _md2(format_monitoring_schedule_line(deployed=bool(dep_file)))

    await _reply_md2(
        message,
        f"🛡 *KAVACH Status*\n\n"
        f"Broker     : {broker_line}\n"
        f"Algo       : {algo_line}\n"
        f"Deployment : {dep_line}\n"
        f"ATO Schedule: {schedule_line}\n"
        f"NIFTY Feed : {nifty_line}\n"
        f"ATO CE     : {'🔴 Triggered' if ce_trig else '🟢 Idle'}\n"
        f"ATO PE     : {'🔴 Triggered' if pe_trig else '🟢 Idle'}",
        reply_markup=_main_menu_keyboard(),
    )


# ── /batman_complete ──────────────────────────────────────────────────────────


async def cmd_dyn_hedge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Yes/No toggle for exiting 30% dynamic hedge on first ATO trigger."""
    message = _require_message(update)
    state = context.bot_data.get("state")
    enabled = bool(state.get("dyn_hedge.exit_enabled", False)) if state else False
    current = "YES" if enabled else "NO"
    # Explain the opposite choice (what changes if they flip the setting).
    if enabled:
        help_line = (
            "_When No : On the first ATO trigger of the day for a side, "
            "that side’s 30% dynamic hedge leg will not be exited\\._"
        )
    else:
        help_line = (
            "_When YES: On the first ATO trigger of the day for a side, "
            "that side’s 30% dynamic hedge leg is exited in full — no re\\-entry\\._"
        )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes", callback_data=f"{_CB_DYN_HEDGE}:yes"
                ),
                InlineKeyboardButton(
                    "❌ No", callback_data=f"{_CB_DYN_HEDGE}:no"
                ),
            ],
            [InlineKeyboardButton("« Main menu", callback_data=f"{_CB_MENU}:main")],
        ]
    )
    await _reply_md2(
        message,
        "🛡 *30% Dynamic Hedge*\n\n"
        "Do you want to exit 30% Qty when ATO triggered\\?\n\n"
        f"Current Setting: *{_md2(current)}*\n\n"
        f"{help_line}",
        reply_markup=keyboard,
    )


async def on_dyn_hedge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _require_query(update)
    await _safe_answer_callback(query)
    message = query.message
    if message is None:
        return
    action = (query.data or "").split(":")[-1]
    state = context.bot_data.get("state")
    if state is None:
        await _reply_md2(
            message,
            "⚠️ State store unavailable\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return
    if action == "yes":
        state.set("dyn_hedge.exit_enabled", True)
        label = "YES"
    elif action == "no":
        state.set("dyn_hedge.exit_enabled", False)
        label = "NO"
    else:
        await _send_alive_menu(message)
        return
    await _reply_md2(
        message,
        f"✅ 30% Dynamic Hedge exit set to *{_md2(label)}*\\.",
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_batman_complete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_paused_command(
        update,
        context,
        bot_name="kavach2",
        read_only_commands=_READ_ONLY_COMMANDS,
    ):
        return
    message = _require_message(update)
    if not _find_active_deployment():
        await _reply_md2(
            message,
            "⚠️ No active deployment to complete\\.",
            reply_markup=_main_menu_keyboard(),
        )
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes — Batman complete", callback_data=f"{_CB_DONE}:confirm"
                ),
                InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_DONE}:cancel"),
            ]
        ]
    )
    await _reply_md2(
        message,
        "🦇 *Batman Complete?*\n\n"
        "This will:\n"
        "• Stop all algo modules \\(ATO, trailing\\)\n"
        "• Archive the deployment file\n"
        "• Clear all state \\(positions, ATO strikes, flags\\)\n"
        "• Reset algo — fresh, ready for next deployment\n\n"
        "_Your positions on Dhan are NOT closed automatically\\._",
        reply_markup=keyboard,
    )


def _batman_complete_locked(
    context: ContextTypes.DEFAULT_TYPE,
    dep_registered_at: str,
    completed_at: str,
) -> tuple[list[str], bool, list[tuple[str, bool]], int]:
    from core.ato_operator_config import ato_operator_settings

    params = context.bot_data.get("params") or {}
    op = ato_operator_settings(params)
    max_attempts = int(op.get("cleanup_retry_max", 3))

    with deployment_session("batman_complete"):
        state = context.bot_data.get("state")
        if state is not None:
            state.set("deployment.confirmed", False, save=True)
        moved = _archive_active_deployments()
        _append_log(
            "batman_complete",
            by="rahul",
            archived=moved,
            registered_at=dep_registered_at,
            completed_at=completed_at,
        )
        _state_reset(state)
        broker = context.bot_data.get("broker")
        if broker is not None and hasattr(broker, "clear_virtual_book"):
            broker.clear_virtual_book()

        def _attempt() -> tuple[list[str], bool, list[tuple[str, bool]]]:
            all_ok, checks = verify_batman_cleanup(
                deploy_dir=_DEPLOY_DIR,
                state_get=state.get if state is not None else None,
            )
            return moved, all_ok, checks

        _, all_ok, checks, used = run_cleanup_with_retries(
            cleanup_fn=_attempt,
            max_attempts=max_attempts,
        )
        if state is not None:
            state.set("deployment.cleanup_failed", not all_ok, save=False)
            if not all_ok:
                state.set(
                    "deployment.cleanup_failed_detail",
                    f"failed after {used} attempt(s)",
                    save=False,
                )
            state.save()

        bus = context.bot_data.get("event_bus")
        if bus:
            from core.event_bus import Event

            bus.publish(Event.BATMAN_COMPLETE, {"by": "kavach", "cleanup_ok": all_ok})
        try:
            from core.saransh_session_sync import saransh_session_complete

            saransh_session_complete()
        except Exception as exc:
            logger.warning("SARANSH session complete soft-failed: %s", exc)
        try:
            from core.feed_recovery import clear_recovery_on_batman_complete

            clear_recovery_on_batman_complete()
        except Exception as exc:
            logger.warning("NIFTY feed recovery reset soft-failed: %s", exc)
        return moved, all_ok, checks, used


async def on_batman_complete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _require_query(update)
    await query.answer()

    if query.data == f"{_CB_DONE}:cancel":
        await query.edit_message_text(
            "✅ Cancelled\\. Batman monitoring continues\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    dep_file = _find_active_deployment()
    dep_registered_at = "unknown"
    dep_file_name = dep_file.name if dep_file else "unknown"
    dep_data: dict | None = None
    open_ato: list[str] = []
    if dep_file:
        try:
            with open(dep_file, encoding="utf-8") as _fh:
                dep_data = json.load(_fh)
            dep_registered_at = dep_data.get("registered_at", "unknown")
            dep_file_name = dep_data.get("file_name", dep_file.name)
        except Exception:
            pass
    try:
        broker = context.bot_data.get("broker")
        sym_qty: dict[str, int] = {}
        if broker is not None:
            positions = broker.get_positions()
            if positions is not None and hasattr(positions, "iterrows"):
                for _, row in positions.iterrows():
                    sym = str(row.get("tradingSymbol") or row.get("tradingsymbol") or "")
                    if sym:
                        sym_qty[sym] = abs(int(row.get("netQty", 0) or 0))
        open_ato = open_ato_protect_lines(dep_data=dep_data, broker_symbols_qty=sym_qty)
    except Exception as exc:
        logger.warning("Open ATO leg scan skipped: %s", exc)

    completed_at = datetime.now().strftime("%A %d\\-%b\\-%Y at %H:%M")

    try:
        moved, all_ok, checks, _used = await asyncio.to_thread(
            _batman_complete_locked,
            context,
            dep_registered_at,
            completed_at,
        )
    except DeploymentLockBusy as exc:
        await _edit_md2(
            query,
            f"⚠️ Batman Complete busy — try again\\.\n\n`{_md2_code(str(exc))}`",
        )
        return
    except Exception as exc:
        logger.error("KAVACH: batman_complete archive failed: %s", exc)
        await _publish_kavach_incident(
            cast(Application, context.application),
            scenario="archive_completion_failure",
            severity="critical",
            category="system",
            title="Batman completion archive failed",
            error_message=str(exc),
            next_action="Review deployment files and complete cleanup manually before the next session.",
            send_to_source=False,
        )
        await query.edit_message_text(
            f"⚠️ Batman completion aborted because deployment archiving failed.\n\nError: {exc}",
        )
        return

    logger.info("KAVACH: batman_complete — deployment archived, state reset (verified=%s)", all_ok)
    archived_name = moved[-1] if moved else dep_file_name
    body = format_cleanup_verification_message(
        all_ok=all_ok,
        checks=checks,
        registered_at=dep_registered_at,
        completed_at=completed_at,
        archived_file=archived_name,
        open_ato_lines=open_ato,
        auto_register=all_ok,
    )
    await _edit_md2(query, body)

    if not all_ok:
        await _publish_kavach_incident(
            cast(Application, context.application),
            scenario="batman_cleanup_failed",
            severity="critical",
            category="system",
            title="Batman cleanup failed after retries",
            error_message="Cleanup verification did not pass — /register blocked",
            next_action="Review failed checks in KAVACH message before re-registering.",
            send_to_source=False,
        )
        return

    if query.message is not None:
        _clear_wizard_data(context)
        ingest_err = await _uat_refresh_book_for_register(context)
        if ingest_err:
            await _wizard_show(
                context,
                query.message,
                f"⚠️ UAT book refresh failed after Batman Complete\\.\n\n"
                f"{_md2(ingest_err)}\n\n"
                "Fix positions\\.json \\(FAST UAT\\), then tap *Register*\\.",
                prefer_edit=True,
            )
            return
        next_state = await _wizard_fetch_step1(
            context, reply_target=query.message, prefer_edit=False
        )
        _set_register_conversation_state(context, update, next_state)


async def on_hedge_box_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = _require_query(update)
    await query.answer()

    payload = (query.data or "").split(":", 2)
    if len(payload) != 3:
        await query.edit_message_text("⚠️ Invalid Hedge Box response payload.")
        return

    _, decision, request_id = payload
    state = context.bot_data.get("state")
    current_request = state.get("ratripal.pending.request_id") if state else None
    if not state or current_request != request_id:
        await query.edit_message_text(
            "⚠️ This Hedge Box request has expired or was already processed.",
        )
        return

    state.set("ratripal.pending.response", decision)
    state.set("ratripal.pending.responded_at", datetime.now().astimezone().isoformat())

    if decision == "deny":
        await query.edit_message_text(
            "❌ Hedge Box denied for today. No automatic hedge buys will be placed in this cycle.",
        )
        return

    await query.edit_message_text(
        "✅ Hedge Box confirmed. RATRIPAL will proceed with broker execution now.",
    )


# ── Hello / unknown commands ──────────────────────────────────────────────────


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Plain-text catch-all — show alive menu (no slash-command list)."""
    message = _require_message(update)
    await _send_alive_menu(message)


def _menu_action_handlers() -> dict[str, Any]:
    """Menu button → handler (resolved at call time for tests and patches)."""
    return {
        # register → ConversationHandler entry (wizard_entry_menu)
        "positions": cmd_positions,
        "ato_status": cmd_ato_status,
        "corelegs": cmd_legs,
        "status": cmd_status,
        "environment": cmd_environment,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "resume_blocked": cmd_resume_blocked,
        "recovery_operator": cmd_recovery_operator,
        "recovery_auto": cmd_recovery_auto,
        "recovery_auto_confirm": cmd_recovery_auto_confirm,
        "batman_complete": cmd_batman_complete,
        "dyn_hedge": cmd_dyn_hedge,
    }



async def _menu_pause_resume_with_alert(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: CallbackQuery,
    message: Message,
    action: str,
) -> None:
    """Pause/Resume from menu — popup alert first (like GO), then chat reply."""
    import re

    fake_update = Update(update.update_id, message=message)

    if action == "pause":
        if not _find_active_deployment():
            await _safe_answer_callback(
                query,
                "⚠️ No deployment registered. Tap Register first.",
                show_alert=True,
            )
            return
        await _safe_answer_callback(
            query,
            "⏸ KAVACH PAUSED — ATO monitoring suspended.",
            show_alert=True,
        )
        await cmd_pause(fake_update, context)
        return

    # resume
    if not _find_active_deployment():
        await _safe_answer_callback(
            query,
            "⚠️ No deployment. Tap Register first.",
            show_alert=True,
        )
        return

    from core.feed_recovery import evaluate_kavach_resume

    state = context.bot_data.get("state")
    pause_reason = state.get("algo.pause_reason") if state else None
    allowed, note = evaluate_kavach_resume(pause_reason)
    if not allowed:
        alert = re.sub(r"<[^>]+>", "", str(note or "Resume blocked."))
        alert = " ".join(alert.split())
        await _safe_answer_callback(query, alert[:180], show_alert=True)
    else:
        await _safe_answer_callback(
            query,
            "▶️ KAVACH RESUMED — ATO monitoring active.",
            show_alert=True,
        )
    await cmd_resume(fake_update, context)



async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route main-menu button taps to existing command handlers."""
    query = _require_query(update)
    message = query.message
    if message is None:
        return

    action = (query.data or "").split(":", 1)[-1]

    # Pause/Resume: GO-style native Telegram popup (answerCallbackQuery show_alert).
    if action in {"pause", "resume"}:
        await _menu_pause_resume_with_alert(update, context, query, message, action)
        return

    await _safe_answer_callback(query)
    if action in {"main", "menu", "ping"}:
        await _send_alive_menu(message)
        return
    if action == "register":
        # ConversationHandler owns register; avoid refreshing menu while wizard runs.
        return
    if action == "ato_tune":
        # ConversationHandler owns ATO Configuration / Quick Tune.
        return
    if action == "deploy_batman2":
        # ConversationHandler owns Deploy Batman 2.0.
        return

    fake_update = Update(update.update_id, message=message)
    handler = _menu_action_handlers().get(action)
    if handler is not None:
        await handler(fake_update, context)
        return

    await _send_alive_menu(message)


async def _wizard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    del update
    _append_log("wizard_cancelled", reason="manual_cancel_command")
    _clear_wizard_data(context)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
# ATO event notifications (EventBus → proactive Telegram messages)
# ═══════════════════════════════════════════════════════════════════════════════


async def _push(app: Application, chat_id: str, text: str) -> None:
    """Send a proactive message to the KAVACH chat (MarkdownV2)."""
    try:
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as exc:
        logger.error("KAVACH push notification failed: %s", exc)


async def _publish_kavach_incident(
    app: Application,
    *,
    scenario: str,
    severity: str,
    category: str,
    title: str,
    error_message: str,
    next_action: str,
    send_to_source: bool = True,
) -> None:
    await publish_incident(
        source="kavach2",
        scenario=scenario,
        severity=severity,
        category=category,
        title=title,
        error_message=error_message,
        next_action=next_action,
        source_bot=app.bot,
        source_chat_id=str(app.bot_data.get("chat_id", "")),
        send_to_source=send_to_source,
    )


def register_event_subscriptions(app: Application) -> None:
    """Subscribe to EventBus events for proactive ATO notifications.

    Called from build_application after bot_data is populated.

    Thread-safety note: EventBus callbacks are invoked from module *threads*,
    not from the asyncio event loop. We use
    ``asyncio.run_coroutine_threadsafe(coro, loop)`` (stored in bot_data by
    main.py) to dispatch the push coroutine safely into the main event loop.
    """
    bus = app.bot_data.get("event_bus")
    chat_id = app.bot_data.get("chat_id", "")
    if not bus or not chat_id:
        logger.warning("KAVACH: event_bus or chat_id missing — skipping subscriptions")
        return

    from core.event_bus import Event

    def _fire(coro) -> None:
        """Dispatch *coro* into the main asyncio loop from any thread."""
        _loop = app.bot_data.get("loop")
        if _loop and _loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, _loop)

            def _log_future_result(fut: asyncio.Future) -> None:
                try:
                    fut.result()
                except Exception as exc:
                    logger.error("KAVACH event push failed: %s", exc)

            future.add_done_callback(_log_future_result)
        else:
            logger.warning("KAVACH: event loop not available — push skipped")

    def _on_ato_ce(event, payload):
        del event
        spot = payload.get("spot")
        spot_txt = (
            f"\nSpot `{_md2_code(f'{float(spot):,.2f}')}`" if spot is not None else ""
        )
        _fire(
            _push(
                app,
                chat_id,
                "🔴 *CE \\- ATO TRIGGERED*\n"
                f"Spot ≥ CE trigger{spot_txt}",
            )
        )

    def _on_ato_pe(event, payload):
        del event
        spot = payload.get("spot")
        spot_txt = (
            f"\nSpot `{_md2_code(f'{float(spot):,.2f}')}`" if spot is not None else ""
        )
        _fire(
            _push(
                app,
                chat_id,
                "🔴 *PE \\- ATO TRIGGERED*\n"
                f"Spot ≤ PE trigger{spot_txt}",
            )
        )

    def _on_ato_ce_exited(event, payload):
        del event
        spot = payload.get("spot")
        spot_txt = (
            f"\nSpot `{_md2_code(f'{float(spot):,.2f}')}`" if spot is not None else ""
        )
        _fire(
            _push(
                app,
                chat_id,
                "🟢 *CE \\- ATO EXITED*\n"
                f"Retrace exit met{spot_txt}",
            )
        )

    def _on_ato_pe_exited(event, payload):
        del event
        spot = payload.get("spot")
        spot_txt = (
            f"\nSpot `{_md2_code(f'{float(spot):,.2f}')}`" if spot is not None else ""
        )
        _fire(
            _push(
                app,
                chat_id,
                "🟢 *PE \\- ATO EXITED*\n"
                f"Retrace exit met{spot_txt}",
            )
        )

    def _on_dyn_hedge_exited(event, payload):
        del event
        side = str(payload.get("side", "")).upper()
        symbol = str(payload.get("symbol", "?"))
        qty = payload.get("qty", "?")
        _fire(
            _push(
                app,
                chat_id,
                f"🛡 *{_md2(side)} \\- 30% Dynamic Hedge EXITED*\n"
                f"`{_md2_code(f'{symbol}  qty={qty}')}`\n"
                "One\\-shot exit on first ATO trigger — no re\\-entry today\\.",
            )
        )

    def _on_max_cycles(event, payload):
        del event
        if payload.get("soft_cap"):
            side = str(payload.get("side", "")).upper()
            exposure = payload.get("exposure", payload.get("cycles", 0))
            _fire(
                _push(
                    app,
                    chat_id,
                    f"⚠️ *{side} \\- ATO Choppy Market* \\(Exposure : {exposure}\\)\n\n"
                    "Manage Buffer if required\\!\n\n"
                    "Warning Only — ATO Continues\\.",
                )
            )
            return
        _fire(
            _push(
                app,
                chat_id,
                "⚠️ *ATO max cycles reached\\.*\n\n"
                "ATO monitoring has stopped cycling\\.\n"
                "Review positions and consider /batman\\_complete\\.",
            )
        )

    def _on_monitor_breach(event, payload):
        del event
        side = str(payload.get("side", "")).upper()
        spot = payload.get("spot", "")
        _fire(
            _push(
                app,
                chat_id,
                f"👁 *ATO {side} breach* \\(monitor\\-only\\)\n\n"
                f"Spot {spot} crossed sell strike\\. ATO lots\\=0 — no order placed\\.",
            )
        )

    def _on_module_error(event, payload):
        del event
        scenario = str(payload.get("scenario", "")).strip()
        if scenario not in {
            "margin_shortfall",
            "order_rejection",
            "hedge_box_execution_failure",
            "hedge_box_verification_failure",
        }:
            return
        _fire(
            _publish_kavach_incident(
                app,
                scenario=scenario,
                severity=str(payload.get("severity", "major")),
                category=str(payload.get("category", "order")),
                title=str(payload.get("title", "ATO module error")),
                error_message=str(payload.get("error_message", "unknown error")),
                next_action=str(
                    payload.get(
                        "next_action",
                        "Review broker order book and available funds immediately.",
                    )
                ),
            )
        )

    def _on_hedge_box_prompt(event, payload):
        del event

        async def _send_prompt() -> None:
            request_id = str(payload.get("request_id", ""))
            dte = payload.get("dte", "?")
            spot = payload.get("spot")
            timeout_seconds = int(payload.get("timeout_seconds", 120) or 120)
            sides = payload.get("sides", [])
            lines = [
                "🛡 *Hedge Box Plan Ready*",
                "",
                (
                    f"Spot: `{_md2_code(f'{float(spot):,.2f}')}`"
                    if isinstance(spot, (int, float))
                    else "Spot: `N/A`"
                ),
                f"DTE : `{_md2_code(dte)}`",
                f"Timeout: `{_md2_code(f'{timeout_seconds} sec')}`",
                "",
            ]
            for side in sides:
                lines.extend(
                    [
                        f"*{_md2(side.get('side', '?'))}* | zone `{_md2_code(side.get('zone', '?'))}`",
                        f"Strike: `{_md2_code(side.get('strike', '-'))}`",
                        f"Qty   : `{_md2_code(side.get('qty', '-'))}`",
                        f"LTP   : `{_md2_code(side.get('option_ltp', '-'))}`",
                        f"BE ref: `{_md2_code(side.get('break_even', '-'))}`",
                        "",
                    ]
                )
            lines.append(
                _md2("Confirm to buy now, deny to skip today. No response will auto-proceed.")
            )
            await app.bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=_hedge_box_keyboard(request_id),
            )

        _fire(_send_prompt())

    def _on_hedge_box_executed(event, payload):
        del event
        side = str(payload.get("side", "?"))
        zone = str(payload.get("zone", "?"))
        symbol = str(payload.get("symbol", "?"))
        qty = payload.get("qty", "?")
        order_id = str(payload.get("order_id", "?"))
        _fire(
            _push(
                app,
                chat_id,
                "✅ *Hedge Box Buy Verified*\n\n"
                f"Side  : `{side}`\n"
                f"Zone  : `{zone}`\n"
                f"Symbol: `{symbol}`\n"
                f"Qty   : `{qty}`\n"
                f"Order : `{order_id}`",
            )
        )

    def _on_deployment_mismatch(event, payload):
        del event
        reason = str(payload.get("reason", ""))
        if reason == "managed_qty_mismatch":
            details = payload.get("details") or []
            _fire(
                _publish_kavach_incident(
                    app,
                    scenario="managed_qty_mismatch",
                    severity="critical",
                    category="positions",
                    title="Managed qty exceeds broker holdings",
                    error_message="; ".join(str(d) for d in details),
                    next_action="Re-register via /register after fixing broker positions.",
                )
            )
            return
        if reason == "manual_protect_adopted":
            side = str(payload.get("side", "?"))
            symbol = str(payload.get("symbol", "?"))
            _fire(
                _push(
                    app,
                    chat_id,
                    "⚠️ *Manual protect adopted*\n\n"
                    f"Side: `{side}`\n"
                    f"Symbol: `{symbol}`\n\n"
                    "Registered protect found on Dhan — exit\\-only; no second BUY on this side\\.",
                )
            )
            return
        if reason in ("manual_protect_full_exit", "manual_protect_partial_exit"):
            side = str(payload.get("side", "?"))
            symbol = str(payload.get("symbol", "?"))
            broker_qty = payload.get("broker_qty", "?")
            expected_qty = payload.get("expected_qty", "?")
            label = "full" if reason == "manual_protect_full_exit" else "partial"
            _fire(
                _publish_kavach_incident(
                    app,
                    scenario=reason,
                    severity="major",
                    category="positions",
                    title=f"Manual protect {label} exit — {side} side paused",
                    error_message=f"{symbol}: broker={broker_qty} expected={expected_qty}",
                    next_action=str(
                        payload.get(
                            "next_action",
                            "Resume side after fixing broker book, or Batman Complete.",
                        )
                    ),
                )
            )
            return
        if reason == "position_book_unreadable":
            _fire(
                _publish_kavach_incident(
                    app,
                    scenario="position_book_unreadable",
                    severity="critical",
                    category="positions",
                    title="ATO position book unreadable",
                    error_message="Broker positions could not be read during ATO poll.",
                    next_action=str(
                        payload.get(
                            "next_action",
                            "Check Dhan portal; Resume when book is readable.",
                        )
                    ),
                )
            )
            return
        if reason == "position_book_recovered":
            _fire(
                _publish_kavach_incident(
                    app,
                    scenario="position_book_recovered",
                    severity="info",
                    category="positions",
                    title="ATO position book recovered",
                    error_message="Position book was unreadable but recovered on retry.",
                    next_action="Monitoring continues — no action required.",
                )
            )

    bus.subscribe(Event.ATO_CE_TRIGGERED, _on_ato_ce)
    bus.subscribe(Event.ATO_PE_TRIGGERED, _on_ato_pe)
    bus.subscribe(Event.ATO_CE_EXITED, _on_ato_ce_exited)
    bus.subscribe(Event.ATO_PE_EXITED, _on_ato_pe_exited)
    bus.subscribe(Event.DYN_HEDGE_EXITED, _on_dyn_hedge_exited)
    bus.subscribe(Event.ATO_MAX_CYCLES_REACHED, _on_max_cycles)
    bus.subscribe(Event.ATO_MONITOR_BREACH, _on_monitor_breach)
    bus.subscribe(Event.MODULE_ERROR, _on_module_error)
    bus.subscribe(Event.DEPLOYMENT_RESTORE_MISMATCH, _on_deployment_mismatch)
    bus.subscribe(Event.HEDGE_BOX_CONFIRMATION_REQUEST, _on_hedge_box_prompt)
    bus.subscribe(Event.HEDGE_BOX_EXECUTED, _on_hedge_box_executed)

    logger.info("KAVACH: event subscriptions registered ✓")


# ═══════════════════════════════════════════════════════════════════════════════
# Bot builder — called from main.py
# ═══════════════════════════════════════════════════════════════════════════════


def build_application(broker=None, state=None, event_bus=None) -> Application:
    """Build and return the KAVACH PTB Application.

    Inject ``broker``, ``state``, and ``event_bus`` so all handlers can
    reach shared runtime objects via ``context.bot_data``.

    Usage (from main.py)::

        from bat_telegram.bots.kavach2 import bot as kavach_bot
        app = kavach_bot.build_application(broker=broker, state=state, event_bus=bus)
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        ...
        await app.updater.stop()
        await app.stop()
    """
    cfg = load_bot_config("kavach2")
    params = cfg.params
    try:
        from core.config import Config

        app_config = Config.load("config/settings.json")
        lot_size = int(app_config.get("strategy.lot_size", 65))
        params.setdefault("strategy", {})
        params["strategy"].setdefault("lot_size", lot_size)
    except Exception:
        params.setdefault("strategy", {})
        params["strategy"].setdefault("lot_size", 65)
    # User lock: 60s max inactivity at each wizard stage.
    timeout = 60

    app = (
        Application.builder()
        .token(cfg.bot_token)
        .concurrent_updates(False)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(60.0)
        .media_write_timeout(60.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(60.0)
        .get_updates_write_timeout(30.0)
        .build()
    )

    # Inject shared objects into bot_data (accessible in every handler)
    app.bot_data["broker"] = broker
    app.bot_data["state"] = state
    app.bot_data["event_bus"] = event_bus
    app.bot_data["chat_id"] = cfg.chat_id
    app.bot_data["params"] = params
    try:
        from core.config import Config

        app.bot_data["config"] = Config.load("config/settings.json")
    except Exception:
        app.bot_data["config"] = None

    # ── Deploy wizard (ConversationHandler) ──────────────────────────────────
    from bat_telegram.bots.kavach2.ato_configuration_wizard import build_ato_tune_handler

    app.add_handler(build_wizard_handler(timeout))
    app.add_handler(build_ato_tune_handler(timeout))
    from bat_telegram.bots.kavach2.deploy_batman2_wizard import build_deploy_batman2_handler
    app.add_handler(build_deploy_batman2_handler(timeout))

    # ── Standard command handlers ─────────────────────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("ato_status", cmd_ato_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("start_algo_now", cmd_start_now))
    app.add_handler(CommandHandler("legs", cmd_legs))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("funds", cmd_funds))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("batman_complete", cmd_batman_complete))

    # ── Inline keyboard callbacks ─────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(on_batman_complete_callback, pattern=f"^{_CB_DONE}:"))
    app.add_handler(CallbackQueryHandler(on_dyn_hedge_callback, pattern=f"^{_CB_DYN_HEDGE}:"))
    app.add_handler(CallbackQueryHandler(on_hedge_box_callback, pattern=f"^{_CB_HB}:"))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=f"^{_CB_MENU}:"))

    # ── Catch-all plain-text handler (hello / invalid) ────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    app.add_error_handler(_on_handler_error)

    # ── Subscribe to EventBus events for proactive notifications ─────────────
    register_event_subscriptions(app)

    async def _bind_event_loop(application: Application) -> None:
        application.bot_data["loop"] = asyncio.get_running_loop()
        logger.info("KAVACH event loop bound for EventBus dispatch")

    app.post_init = _bind_event_loop
    app.post_stop = cleanup_managed_runtime

    logger.info("KAVACH bot application built ✓")
    return app
