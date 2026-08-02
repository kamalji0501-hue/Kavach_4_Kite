"""KAVACH /register wizard — side-scoped legs, partial lots, custom buffers (§12 + §13)."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, cast

from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from core.buffer_config.schema import (
    BufferKind,
    serialize_buffer_field,
)
from core.buffer_config.levels import (
    format_buffer_with_level,
    parse_and_validate_user_buffer_or_level,
)
from core.position_scope import (
    auto_protect_strike,
    filter_positions_by_direction,
    filter_positions_by_side,
    parse_and_validate_protect_strike,
    qty_to_lots,
    resolve_nifty_lot_size,
    suggested_ato_lots,
)
from core.positions import build_ato_protect_symbol
from core.wizard_plan import (
    question_index,
    rebuild_wizard_plan,
    step_meta,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

logger = logging.getLogger("batman.kavach2.wizard")

WIZARD_CONVERSATION_NAME = "kavach2_register"

# ── Conversation states ───────────────────────────────────────────────────────
(
    WIZARD_PRE_CONFIRM,
    WIZARD_PE_INTENT,
    WIZARD_PE_BUY,
    WIZARD_PE_SELL,
    WIZARD_PE_LOTS,
    WIZARD_PE_ATO_LOTS,
    WIZARD_PE_ATO_STRIKE,
    WIZARD_PE_ATO_STRIKE_CUSTOM,
    WIZARD_CE_INTENT,
    WIZARD_CE_BUY,
    WIZARD_CE_SELL,
    WIZARD_CE_LOTS,
    WIZARD_CE_ATO_LOTS,
    WIZARD_CE_ATO_STRIKE,
    WIZARD_CE_ATO_STRIKE_CUSTOM,
    WIZARD_CE_ENTRY_MODE,
    WIZARD_CE_ENTRY_CUSTOM,
    WIZARD_PE_ENTRY_MODE,
    WIZARD_PE_ENTRY_CUSTOM,
    WIZARD_CE_EXIT_MODE,
    WIZARD_CE_EXIT_CUSTOM,
    WIZARD_PE_EXIT_MODE,
    WIZARD_PE_EXIT_CUSTOM,
    WIZARD_POLL_INTERVAL,
    WIZARD_ATO_MON,
    WIZARD_CONFIRM,
) = range(26)

_CB_PRE = "wiz_pre"
_CB_LEG = "wiz_leg"
_CB_SIDE = "wiz_side"
_CB_LOTS = "wiz_lots"
_CB_ATO_STR = "wiz_astr"
_CB_BUF_MODE = "wiz_bmode"
_CB_BUF = "wiz_buf"
_CB_POLL = "wiz_poll"
_CB_ATO_MON = "wiz_ato_mon"
_CB_CONF = "wiz_conf"

_PE_BUFFER_SEQUENCE = ("pe_entry", "pe_exit")
_CE_BUFFER_SEQUENCE = ("ce_entry", "ce_exit")


def _ato_step(context: ContextTypes.DEFAULT_TYPE) -> int:
    params = context.bot_data.get("params") or {}
    return int((params.get("deploy_wizard") or {}).get("ato_step", 50))


def _qheader(context: ContextTypes.DEFAULT_TYPE, step_id: str, body: str) -> str:
    step_id = _str_step_target(step_id)
    b = _bot()
    wiz = _wiz(context)
    plan = wiz.get("wiz_plan") or rebuild_wizard_plan(wiz)
    idx, total = question_index(plan, step_id)
    _section, label = step_meta(step_id)
    return (
        f"*Question {b._md2(str(idx))} of {b._md2(str(total))} — "
        f"{b._md2(label)}*\n\n{body}"
    )


def _apply_full_side_qty(wiz: dict[str, Any], side: str, lot_size: int) -> None:
    """Use full broker qty (no managed-lots picker) and fix ATO lots to BUY lots."""
    side_l = side.lower()
    buy = wiz[f"{side_l}_buy"]
    buy_qty = abs(int(buy["qty"]))
    managed = qty_to_lots(buy_qty, lot_size)
    wiz[f"{side_l}_managed_lots"] = managed
    wiz[f"{side_l}_ato_lots"] = suggested_ato_lots(managed, buy_qty, lot_size=lot_size)


def _auto_ato_manage_sides(wiz: dict[str, Any]) -> str:
    pe = bool(wiz.get("pe_enabled"))
    ce = bool(wiz.get("ce_enabled"))
    if pe and ce:
        return "both"
    if pe:
        return "pe"
    return "ce"


def _store_protect_strike(wiz: dict[str, Any], side: str, strike: int, mode: str) -> None:
    side_l = side.lower()
    sell = wiz[f"{side_l}_sell"]
    opt = side.upper()
    wiz[f"{side_l}_protect_strike"] = int(strike)
    wiz[f"{side_l}_protect_strike_mode"] = mode
    wiz[f"{side_l}_protect_symbol"] = build_ato_protect_symbol(
        str(sell["symbol"]), int(strike), opt
    )


def _ato_strike_keyboard(side: str) -> InlineKeyboardMarkup:
    side_l = side.lower()
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm",
                    callback_data=f"{_CB_ATO_STR}:{side_l}:confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    "Custom Strike",
                    callback_data=f"{_CB_ATO_STR}:{side_l}:custom",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data=f"{_CB_ATO_STR}:{side_l}:cancel",
                )
            ],
        ]
    )


def _parse_ato_strike_callback(data: str) -> tuple[str, str]:
    """Parse wiz_astr:{side}:{action}."""
    parts = (data or "").split(":")
    side = parts[1] if len(parts) > 1 else ""
    action = parts[2] if len(parts) > 2 else ""
    return side, action


def _ato_strike_prompt_body(side: str, sell_strike: int, auto_strike: int) -> str:
    b = _bot()
    side_esc = b._md2(side.upper())
    return (
        f"{side_esc} SELL strike: `{sell_strike:,}`\n"
        f"ATO \\(auto\\): `{auto_strike:,} {side.upper()}`\n\n"
        f"Confirm auto strike, or tap *Custom Strike* to enter a NIFTY level\\."
    )


def _bot():
    import bat_telegram.bots.kavach2.bot as bot_mod

    return bot_mod


def _wiz(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return cast(dict[str, Any], context.user_data)


def _predefined_lists(context: ContextTypes.DEFAULT_TYPE) -> tuple[list[int], list[int]]:
    """Deprecated — predefined point grids removed (NIFTY levels only)."""
    del context
    return [], []


def _lot_size(context: ContextTypes.DEFAULT_TYPE) -> int:
    params = context.bot_data.get("params") or {}
    config_lot = int((params.get("strategy") or {}).get("lot_size", 0) or 0)
    app_config = context.bot_data.get("config")
    if app_config is not None:
        try:
            config_lot = int(app_config.get("strategy.lot_size", config_lot) or config_lot)
        except Exception:
            pass

    broker_lot: int | None = None
    broker = context.bot_data.get("broker")
    if broker:
        try:
            broker_lot = int(broker.get_lot_size("NIFTY"))
        except Exception:
            pass

    return resolve_nifty_lot_size(
        config_lot_size=config_lot or None,
        broker_lot_size=broker_lot,
    )


def _position_label(pos: dict, lot_size: int) -> str:
    qty = abs(int(pos.get("qty", 0)))
    lots = qty_to_lots(qty, lot_size)
    return (
        f"{pos['symbol']} | {pos['direction']} {qty} qty ({lots} lots) "
        f"| avg ₹{pos['avg_price']}"
    )


def _positions_keyboard(available: list[dict], lot_size: int) -> InlineKeyboardMarkup:
    buttons = []
    for i, pos in enumerate(available):
        buttons.append(
            [InlineKeyboardButton(_position_label(pos, lot_size), callback_data=f"{_CB_LEG}:{i}")]
        )
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_LEG}:cancel")])
    return InlineKeyboardMarkup(buttons)


def _ato_lots_prompt_md(
    context: ContextTypes.DEFAULT_TYPE, side: str, managed_lots: int, suggested: int
) -> str:
    del context, side, managed_lots, suggested
    return ""


def _lots_prompt_md(
    context: ContextTypes.DEFAULT_TYPE,
    side: str,
    buy_qty: int,
    sell_qty: int,
    lot_size: int,
) -> str:
    del context, side, buy_qty, sell_qty, lot_size
    return ""


def pe_intent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Enable PE", callback_data=f"{_CB_SIDE}:pe:enable"),
                InlineKeyboardButton("Skip PE", callback_data=f"{_CB_SIDE}:pe:skip"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_SIDE}:pe:cancel")],
        ]
    )


def ce_intent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Enable CE", callback_data=f"{_CB_SIDE}:ce:enable"),
                InlineKeyboardButton("Skip CE", callback_data=f"{_CB_SIDE}:ce:skip"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_SIDE}:ce:cancel")],
        ]
    )


def _lots_keyboard(side: str, max_lots: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in range(1, max_lots + 1):
        row.append(InlineKeyboardButton(str(n), callback_data=f"{_CB_LOTS}:{side}:{n}"))
        if len(row) >= 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton(f"Use all ({max_lots})", callback_data=f"{_CB_LOTS}:{side}:all")]
    )
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_LOTS}:cancel")])
    return InlineKeyboardMarkup(rows)


def _buffer_mode_keyboard(target: str) -> InlineKeyboardMarkup:
    """Cancel-only while waiting for a typed NIFTY level."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_BUF_MODE}:{target}:cancel")],
        ]
    )


def _predefined_buffer_keyboard(target: str, options: list[int]) -> InlineKeyboardMarkup:
    """Deprecated stub — predefined point pickers removed."""
    del options
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_BUF}:cancel")]]
    )


def _ato_monitor_keyboard(pe_enabled: bool, ce_enabled: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if pe_enabled:
        rows.append([InlineKeyboardButton("PE side only", callback_data=f"{_CB_ATO_MON}:pe")])
    if ce_enabled:
        rows.append([InlineKeyboardButton("CE side only", callback_data=f"{_CB_ATO_MON}:ce")])
    if pe_enabled and ce_enabled:
        rows.append([InlineKeyboardButton("Both sides", callback_data=f"{_CB_ATO_MON}:both")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_ATO_MON}:cancel")])
    return InlineKeyboardMarkup(rows)


def _selected_for_header(wiz: dict) -> dict:
    sel = {}
    for k in ("pe_buy", "pe_sell", "ce_buy", "ce_sell"):
        if wiz.get(k):
            sel[k] = wiz[k]
    return sel


def _sync_wiz_selected(wiz: dict) -> None:
    wiz["wiz_selected"] = _selected_for_header(wiz)


def _wiz_key_for_target(target: str) -> str:
    return {
        "ce_entry": "wiz_ce_entry_buffer",
        "pe_entry": "wiz_pe_entry_buffer",
        "ce_exit": "wiz_ce_exit_buffer",
        "pe_exit": "wiz_pe_exit_buffer",
    }[target]


def _custom_state_for_target(target: str) -> int:
    return {
        "ce_entry": WIZARD_CE_ENTRY_CUSTOM,
        "pe_entry": WIZARD_PE_ENTRY_CUSTOM,
        "ce_exit": WIZARD_CE_EXIT_CUSTOM,
        "pe_exit": WIZARD_PE_EXIT_CUSTOM,
    }[target]


def _mode_state_for_target(target: str) -> int:
    return {
        "ce_entry": WIZARD_CE_ENTRY_MODE,
        "pe_entry": WIZARD_PE_ENTRY_MODE,
        "ce_exit": WIZARD_CE_EXIT_MODE,
        "pe_exit": WIZARD_PE_EXIT_MODE,
    }[target]


def _str_step_target(target: Any) -> str:
    """Callback step id must be str (guard against bad split / legacy state)."""
    if isinstance(target, str):
        return target
    if isinstance(target, (tuple, list)) and target:
        return str(target[0])
    return str(target)


def _side_enabled(wiz: dict, target: str) -> bool:
    target = _str_step_target(target)
    if target.startswith("ce"):
        return bool(wiz.get("ce_enabled"))
    return bool(wiz.get("pe_enabled"))


def _buffer_kind_label(target: str, *, for_message: bool = True) -> str:
    """MD2-safe label; use for_message=False for plain button/log text."""
    if "entry" in target:
        return "entry"
    return "exit \\(retrace\\)" if for_message else "exit (retrace)"


def _buffer_step_title(context: ContextTypes.DEFAULT_TYPE, target: str) -> str:
    target = _str_step_target(target)
    side = "CE" if target.startswith("ce") else "PE"
    step_id = target
    kind = "entry" if "entry" in target else "exit"
    kind_hint = "fire" if kind == "entry" else "retrace exit"
    body = f"Enter *{side} {kind}* NIFTY level \\(where ATO should {kind_hint}\\):"
    return _qheader(context, step_id, body)


def _next_in_sequence(seq: tuple[str, ...], after: str | None) -> str | None:
    if after is None:
        return seq[0] if seq else None
    try:
        idx = seq.index(after) + 1
    except ValueError:
        return None
    return seq[idx] if idx < len(seq) else None


async def _cancel_wizard(query, context) -> int:
    b = _bot()
    b._append_log("wizard_cancelled")
    b._clear_wizard_data(context)
    await b._wizard_edit_step(
        context, query, "❌ Deployment cancelled\\. Run /register when ready\\."
    )
    return ConversationHandler.END


async def _ask_pe_buy_legs(query_or_msg, context, *, prefer_edit: bool = True) -> int:
    """Show PE BUY leg picker (first real Register step — no Enable PE prompt)."""
    b = _bot()
    wiz = _wiz(context)
    wiz["pe_enabled"] = True
    rebuild_wizard_plan(wiz)
    all_pos = cast(list[dict], wiz["wiz_positions"])
    long_pe = filter_positions_by_direction(filter_positions_by_side(all_pos, "PE"), "LONG")
    lot_size = _lot_size(context)
    body = "Select your *Core PE BUY* leg:"
    text = _qheader(context, "pe_buy", body)
    kb = _positions_keyboard(long_pe, lot_size)
    wiz["_pe_pick_pool"] = long_pe
    if prefer_edit and hasattr(query_or_msg, "edit_message_text"):
        await b._wizard_edit_step(context, query_or_msg, text, reply_markup=kb)
    else:
        await b._wizard_show(context, query_or_msg, text, reply_markup=kb, prefer_edit=prefer_edit)
    return WIZARD_PE_BUY


async def _ask_ce_buy_legs(query_or_msg, context, *, prefer_edit: bool = True) -> int:
    """Show CE BUY leg picker (no Enable CE prompt)."""
    b = _bot()
    wiz = _wiz(context)
    wiz["ce_enabled"] = True
    rebuild_wizard_plan(wiz)
    all_pos = cast(list[dict], wiz["wiz_positions"])
    long_ce = filter_positions_by_direction(filter_positions_by_side(all_pos, "CE"), "LONG")
    lot_size = _lot_size(context)
    body = "Select your *Core CE BUY* leg:"
    text = _qheader(context, "ce_buy", body)
    kb = _positions_keyboard(long_ce, lot_size)
    wiz["_ce_pick_pool"] = long_ce
    if prefer_edit and hasattr(query_or_msg, "edit_message_text"):
        # CallbackQuery path
        await b._wizard_edit_step(context, query_or_msg, text, reply_markup=kb)
    elif prefer_edit and getattr(query_or_msg, "data", None) is not None:
        await b._wizard_edit_step(context, query_or_msg, text, reply_markup=kb)
    else:
        # Message or reply_target from batman_complete
        show = getattr(b, "_wizard_show", None)
        if show and not hasattr(query_or_msg, "data"):
            await show(context, query_or_msg, text, reply_markup=kb, prefer_edit=prefer_edit)
        else:
            await b._wizard_edit_step(context, query_or_msg, text, reply_markup=kb)
    return WIZARD_CE_BUY


async def begin_register_leg_pick(
    context: ContextTypes.DEFAULT_TYPE,
    reply_target,
    *,
    prefer_edit: bool = False,
) -> int:
    """Start Register at PE/CE leg pick — skips Enable PE / Enable CE prompts."""
    b = _bot()
    wiz = _wiz(context)
    all_pos = cast(list[dict], wiz.get("wiz_positions") or [])
    long_pe = filter_positions_by_direction(filter_positions_by_side(all_pos, "PE"), "LONG")
    long_ce = filter_positions_by_direction(filter_positions_by_side(all_pos, "CE"), "LONG")
    pe_ok = bool(long_pe)
    ce_ok = bool(long_ce)
    if not pe_ok and not ce_ok:
        await b._wizard_show(
            context,
            reply_target,
            "⚠️ No PE/CE BUY candidates found to register\\.\n\n"
            "UAT book needs BUY legs on PE and/or CE\\. "
            "Check positions book, then tap *Register* again\\.",
            prefer_edit=prefer_edit,
        )
        b._clear_wizard_data(context)
        return ConversationHandler.END

    wiz["pe_enabled"] = pe_ok
    wiz["ce_enabled"] = ce_ok
    rebuild_wizard_plan(wiz)

    if pe_ok:
        lot_size = _lot_size(context)
        body = "Select your *Core PE BUY* leg:"
        text = _qheader(context, "pe_buy", body)
        kb = _positions_keyboard(long_pe, lot_size)
        wiz["_pe_pick_pool"] = long_pe
        await b._wizard_show(
            context, reply_target, text, reply_markup=kb, prefer_edit=prefer_edit
        )
        return WIZARD_PE_BUY

    lot_size = _lot_size(context)
    body = "Select your *Core CE BUY* leg:"
    text = _qheader(context, "ce_buy", body)
    kb = _positions_keyboard(long_ce, lot_size)
    wiz["_ce_pick_pool"] = long_ce
    await b._wizard_show(
        context, reply_target, text, reply_markup=kb, prefer_edit=prefer_edit
    )
    return WIZARD_CE_BUY


async def wizard_pe_intent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy Enable PE screen — skip straight to PE BUY (or CE if no PE)."""
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    data = query.data or ""
    if data.endswith(":cancel"):
        return await _cancel_wizard(query, context)
    # Enable / Skip both proceed into auto leg-pick (no stuck intent UI).
    return await begin_register_leg_pick(context, query.message, prefer_edit=True)


async def _goto_ce_intent(query, context) -> int:
    """Skip Enable CE prompt — go to CE BUY or poll if CE not available."""
    return await _start_ce_or_poll(query, context, via_message=False)


async def _goto_ce_intent_message(message, context) -> int:
    return await _start_ce_or_poll(message, context, via_message=True)


async def _start_ce_or_poll(target, context, *, via_message: bool) -> int:
    b = _bot()
    wiz = _wiz(context)
    all_pos = cast(list[dict], wiz.get("wiz_positions") or [])
    long_ce = filter_positions_by_direction(filter_positions_by_side(all_pos, "CE"), "LONG")
    if not long_ce:
        wiz["ce_enabled"] = False
        rebuild_wizard_plan(wiz)
        if via_message:
            body = "Select:"
            await b._reply_md2(
                target,
                _qheader(context, "poll", body),
                reply_markup=b._poll_interval_keyboard(),
            )
            return WIZARD_POLL_INTERVAL
        return await _goto_poll(target, context)
    wiz["ce_enabled"] = True
    rebuild_wizard_plan(wiz)
    lot_size = _lot_size(context)
    body = "Select your *Core CE BUY* leg:"
    text = _qheader(context, "ce_buy", body)
    kb = _positions_keyboard(long_ce, lot_size)
    wiz["_ce_pick_pool"] = long_ce
    if via_message:
        await b._reply_md2(target, text, reply_markup=kb)
    else:
        await b._wizard_edit_step(context, target, text, reply_markup=kb)
    return WIZARD_CE_BUY


async def wizard_ce_intent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy Enable CE screen — skip straight to CE BUY / poll."""
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    data = query.data or ""
    if data.endswith(":cancel"):
        return await _cancel_wizard(query, context)
    return await _goto_ce_intent(query, context)


async def wizard_pe_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    pool = cast(list[dict], wiz.get("_pe_pick_pool", []))
    if query.data == f"{_CB_LEG}:cancel":
        return await _cancel_wizard(query, context)
    idx = int((query.data or "").split(":")[-1])
    wiz["pe_buy"] = pool[idx]
    used = {pool[idx]["symbol"]}
    all_pos = cast(list[dict], wiz["wiz_positions"])
    short_pe = [
        p
        for p in filter_positions_by_direction(filter_positions_by_side(all_pos, "PE"), "SHORT")
        if p["symbol"] not in used
    ]
    header = b._selected_header(_selected_for_header(wiz))
    lot_size = _lot_size(context)
    body = f"{header}\n\nSelect your *PE SELL* leg:"
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "pe_sell", body),
        reply_markup=_positions_keyboard(short_pe, lot_size),
    )
    wiz["_pe_pick_pool"] = short_pe
    return WIZARD_PE_SELL


async def wizard_pe_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    pool = cast(list[dict], wiz.get("_pe_pick_pool", []))
    if query.data == f"{_CB_LEG}:cancel":
        return await _cancel_wizard(query, context)
    idx = int((query.data or "").split(":")[-1])
    pe_sell = pool[idx]
    wiz["pe_sell"] = pe_sell
    _apply_full_side_qty(wiz, "PE", _lot_size(context))
    return await _ask_pe_ato_strike(query, context)


async def wizard_pe_lots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy no-op — managed lots removed in Kavach 2.0."""
    del update, context
    return ConversationHandler.END


async def _ask_pe_ato_lots(query, context) -> int:
    return await _ask_pe_ato_strike(query, context)


async def wizard_pe_ato_lots_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    del update, context
    return ConversationHandler.END


async def _ask_pe_ato_strike(query, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    step = _ato_step(context)
    sell_strike = int(wiz["pe_sell"]["strike"])
    auto_strike = auto_protect_strike(sell_strike, "PE", ato_step=step)
    wiz["_pe_auto_protect_strike"] = auto_strike
    body = _ato_strike_prompt_body("PE", sell_strike, auto_strike)
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "pe_ato_strike", body),
        reply_markup=_ato_strike_keyboard("PE"),
    )
    return WIZARD_PE_ATO_STRIKE


async def _ask_pe_ato_strike_message(message, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    step = _ato_step(context)
    sell_strike = int(wiz["pe_sell"]["strike"])
    auto_strike = auto_protect_strike(sell_strike, "PE", ato_step=step)
    wiz["_pe_auto_protect_strike"] = auto_strike
    body = _ato_strike_prompt_body("PE", sell_strike, auto_strike)
    await b._reply_md2(
        message,
        _qheader(context, "pe_ato_strike", body),
        reply_markup=_ato_strike_keyboard("PE"),
    )
    return WIZARD_PE_ATO_STRIKE


async def wizard_pe_ato_strike(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    _side, action = _parse_ato_strike_callback(query.data or "")
    if action == "cancel":
        return await _cancel_wizard(query, context)
    if action == "custom":
        body = (
            "Enter *PE ATO protect strike* \\(NIFTY level\\)\\.\n"
            "Must be a whole number on the NIFTY grid \\(multiple of 50\\)\\.\n"
            "Example: `24200`"
        )
        await b._wizard_edit_step(context, query, _qheader(context, "pe_ato_strike", body))
        return WIZARD_PE_ATO_STRIKE_CUSTOM
    if action == "confirm":
        auto_strike = int(wiz.get("_pe_auto_protect_strike", 0))
        _store_protect_strike(wiz, "PE", auto_strike, "FIXED")
        return await _ask_buffer_mode(query, context, "pe_entry")
    return WIZARD_PE_ATO_STRIKE


async def wizard_pe_ato_strike_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    wiz = _wiz(context)
    value, err = parse_and_validate_protect_strike(message.text or "")
    if err:
        await message.reply_text(f"❌ {err}")
        return WIZARD_PE_ATO_STRIKE_CUSTOM
    _store_protect_strike(wiz, "PE", value, "CUSTOM")
    return await _ask_nifty_level_message(message, context, "pe_entry")


async def wizard_ce_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    pool = cast(list[dict], wiz.get("_ce_pick_pool", []))
    if query.data == f"{_CB_LEG}:cancel":
        return await _cancel_wizard(query, context)
    idx = int((query.data or "").split(":")[-1])
    wiz["ce_buy"] = pool[idx]
    used = {pool[idx]["symbol"]}
    all_pos = cast(list[dict], wiz["wiz_positions"])
    short_ce = [
        p
        for p in filter_positions_by_direction(filter_positions_by_side(all_pos, "CE"), "SHORT")
        if p["symbol"] not in used
    ]
    header = b._selected_header(_selected_for_header(wiz))
    lot_size = _lot_size(context)
    body = f"{header}\n\nSelect your *CE SELL* leg:"
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "ce_sell", body),
        reply_markup=_positions_keyboard(short_ce, lot_size),
    )
    wiz["_ce_pick_pool"] = short_ce
    return WIZARD_CE_SELL


async def wizard_ce_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    pool = cast(list[dict], wiz.get("_ce_pick_pool", []))
    if query.data == f"{_CB_LEG}:cancel":
        return await _cancel_wizard(query, context)
    idx = int((query.data or "").split(":")[-1])
    ce_sell = pool[idx]
    wiz["ce_sell"] = ce_sell
    _apply_full_side_qty(wiz, "CE", _lot_size(context))
    return await _ask_ce_ato_strike(query, context)


async def wizard_ce_lots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy no-op — managed lots removed in Kavach 2.0."""
    del update, context
    return ConversationHandler.END


async def _ask_ce_ato_lots(query, context) -> int:
    return await _ask_ce_ato_strike(query, context)


async def wizard_ce_ato_lots_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    del update, context
    return ConversationHandler.END


async def _ask_ce_ato_strike(query, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    step = _ato_step(context)
    sell_strike = int(wiz["ce_sell"]["strike"])
    auto_strike = auto_protect_strike(sell_strike, "CE", ato_step=step)
    wiz["_ce_auto_protect_strike"] = auto_strike
    body = _ato_strike_prompt_body("CE", sell_strike, auto_strike)
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "ce_ato_strike", body),
        reply_markup=_ato_strike_keyboard("CE"),
    )
    return WIZARD_CE_ATO_STRIKE


async def _ask_ce_ato_strike_message(message, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    step = _ato_step(context)
    sell_strike = int(wiz["ce_sell"]["strike"])
    auto_strike = auto_protect_strike(sell_strike, "CE", ato_step=step)
    wiz["_ce_auto_protect_strike"] = auto_strike
    body = _ato_strike_prompt_body("CE", sell_strike, auto_strike)
    await b._reply_md2(
        message,
        _qheader(context, "ce_ato_strike", body),
        reply_markup=_ato_strike_keyboard("CE"),
    )
    return WIZARD_CE_ATO_STRIKE


async def wizard_ce_ato_strike(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    _side, action = _parse_ato_strike_callback(query.data or "")
    if action == "cancel":
        return await _cancel_wizard(query, context)
    if action == "custom":
        body = (
            "Enter *CE ATO protect strike* \\(NIFTY level\\)\\.\n"
            "Must be a whole number on the NIFTY grid \\(multiple of 50\\)\\.\n"
            "Example: `24350`"
        )
        await b._wizard_edit_step(context, query, _qheader(context, "ce_ato_strike", body))
        return WIZARD_CE_ATO_STRIKE_CUSTOM
    if action == "confirm":
        auto_strike = int(wiz.get("_ce_auto_protect_strike", 0))
        _store_protect_strike(wiz, "CE", auto_strike, "FIXED")
        return await _ask_buffer_mode(query, context, "ce_entry")
    return WIZARD_CE_ATO_STRIKE


async def wizard_ce_ato_strike_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    wiz = _wiz(context)
    value, err = parse_and_validate_protect_strike(message.text or "")
    if err:
        await message.reply_text(f"❌ {err}")
        return WIZARD_CE_ATO_STRIKE_CUSTOM
    _store_protect_strike(wiz, "CE", value, "CUSTOM")
    return await _ask_nifty_level_message(message, context, "ce_entry")


async def _ask_buffer_mode(query, context, target: str) -> int:
    """Prompt for a NIFTY level (predefined points removed)."""
    b = _bot()
    wiz = _wiz(context)
    wiz["_buf_custom_target"] = target
    side = "CE" if target.startswith("ce") else "PE"
    sell_key = "ce_sell" if side == "CE" else "pe_sell"
    sell_leg = wiz.get(sell_key) or {}
    sell = (
        int(sell_leg["strike"])
        if isinstance(sell_leg, dict) and sell_leg.get("strike") is not None
        else None
    )
    sell_hint = f"\nSell strike: `{sell:,}`" if sell is not None else ""
    await b._wizard_edit_step(
        context,
        query,
        f"{_buffer_step_title(context, target)}{sell_hint}\n\nExample: `24160`",
        reply_markup=_buffer_mode_keyboard(target),
    )
    return _custom_state_for_target(target)


async def _ask_nifty_level_message(message, context, target: str) -> int:
    """Same as `_ask_buffer_mode` but for a plain Message reply path."""
    b = _bot()
    wiz = _wiz(context)
    wiz["_buf_custom_target"] = target
    side = "CE" if target.startswith("ce") else "PE"
    sell_key = "ce_sell" if side == "CE" else "pe_sell"
    sell_leg = wiz.get(sell_key) or {}
    sell = (
        int(sell_leg["strike"])
        if isinstance(sell_leg, dict) and sell_leg.get("strike") is not None
        else None
    )
    sell_hint = f"\nSell strike: `{sell:,}`" if sell is not None else ""
    await b._reply_md2(
        message,
        f"{_buffer_step_title(context, target)}{sell_hint}\n\nExample: `24160`",
        reply_markup=_buffer_mode_keyboard(target),
    )
    return _custom_state_for_target(target)


async def wizard_buffer_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel (or legacy pred/custom taps) during NIFTY-level entry."""
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    parts = (query.data or "").split(":")
    target = _str_step_target(parts[1] if len(parts) > 1 else "")
    action = parts[2] if len(parts) > 2 else ""
    if action == "cancel":
        return await _cancel_wizard(query, context)
    # Legacy Predefined/Custom buttons → re-prompt for NIFTY level.
    return await _ask_buffer_mode(query, context, target)


async def wizard_buffer_predefined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy predefined-point callbacks → redirect to NIFTY level entry."""
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    if query.data == f"{_CB_BUF}:cancel":
        return await _cancel_wizard(query, context)
    parts = (query.data or "").split(":")
    target = _str_step_target(parts[1] if len(parts) > 1 else "ce_entry")
    return await _ask_buffer_mode(query, context, target)


async def wizard_buffer_custom_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    wiz = _wiz(context)
    target = str(wiz.get("_buf_custom_target", "ce_entry"))
    side = "CE" if target.startswith("ce") else "PE"
    kind = "entry" if "entry" in target else "exit"
    sell_key = "ce_sell" if side == "CE" else "pe_sell"
    sell_leg = wiz.get(sell_key) or {}
    sell = (
        int(sell_leg["strike"])
        if isinstance(sell_leg, dict) and sell_leg.get("strike") is not None
        else None
    )
    params = context.bot_data.get("params") or {}
    ato = params.get("ato", {})
    value, err, _mode = parse_and_validate_user_buffer_or_level(
        message.text or "",
        side=side,
        kind=kind,
        sell_strike=sell,
        min_value=Decimal(str(ato.get("buffer_min", "-500"))),
        max_value=Decimal(str(ato.get("buffer_max", "100"))),
    )
    if err:
        await message.reply_text(f"❌ {err}")
        return _custom_state_for_target(target)
    wiz[_wiz_key_for_target(target)] = serialize_buffer_field(value, BufferKind.CUSTOM)
    if sell is not None and value is not None:
        shown = format_buffer_with_level(value, side=side, kind=kind, sell_strike=sell)
        await message.reply_text(f"✅ Stored as {shown}")
    return await _advance_after_buffer_message(message, context, target)


async def _advance_after_buffer(query, context, target: str) -> int:
    target = _str_step_target(target)
    if target.startswith("pe"):
        nxt = _next_in_sequence(_PE_BUFFER_SEQUENCE, target)
        if nxt:
            return await _ask_buffer_mode(query, context, nxt)
        return await _goto_ce_intent(query, context)
    nxt = _next_in_sequence(_CE_BUFFER_SEQUENCE, target)
    if nxt:
        return await _ask_buffer_mode(query, context, nxt)
    return await _goto_poll(query, context)


async def _advance_after_buffer_message(message, context, target: str) -> int:
    target = _str_step_target(target)
    b = _bot()
    if target.startswith("pe"):
        nxt = _next_in_sequence(_PE_BUFFER_SEQUENCE, target)
        if nxt:
            return await _ask_nifty_level_message(message, context, nxt)
        return await _goto_ce_intent_message(message, context)
    nxt = _next_in_sequence(_CE_BUFFER_SEQUENCE, target)
    if nxt:
        return await _ask_nifty_level_message(message, context, nxt)
    body = "Select:"
    await b._reply_md2(
        message,
        _qheader(context, "poll", body),
        reply_markup=b._poll_interval_keyboard(),
    )
    return WIZARD_POLL_INTERVAL


async def _goto_poll(query, context) -> int:
    b = _bot()
    body = "Select:"
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "poll", body),
        reply_markup=b._poll_interval_keyboard(),
    )
    return WIZARD_POLL_INTERVAL


async def wizard_poll_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    if query.data == f"{_CB_POLL}:cancel":
        return await _cancel_wizard(query, context)
    wiz["wiz_poll_interval_seconds"] = int((query.data or "").split(":")[-1])
    wiz["wiz_ato_manage_sides"] = _auto_ato_manage_sides(wiz)
    b._wizard_seed_trading_calendar_defaults(wiz)
    _sync_wiz_selected(wiz)
    return await b._wizard_show_summary(query, context)


async def wizard_ato_mon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy no-op — ATO monitoring mode is auto-set in Kavach 2.0."""
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    wiz["wiz_ato_manage_sides"] = _auto_ato_manage_sides(wiz)
    b._wizard_seed_trading_calendar_defaults(wiz)
    _sync_wiz_selected(wiz)
    return await b._wizard_show_summary(query, context)


def build_wizard_handler(timeout: int) -> ConversationHandler:
    b = _bot()

    return ConversationHandler(
        allow_reentry=True,
        name=WIZARD_CONVERSATION_NAME,
        entry_points=[
            CommandHandler("register", b.wizard_entry),
            CallbackQueryHandler(b.wizard_entry_menu, pattern=f"^{b._CB_MENU}:register$"),
        ],
        states={
            WIZARD_PRE_CONFIRM: [
                CallbackQueryHandler(b.wizard_pre_confirm, pattern=f"^{_CB_PRE}:")
            ],
            WIZARD_PE_INTENT: [CallbackQueryHandler(wizard_pe_intent, pattern=f"^{_CB_SIDE}:pe:")],
            WIZARD_PE_BUY: [CallbackQueryHandler(wizard_pe_buy, pattern=f"^{_CB_LEG}:")],
            WIZARD_PE_SELL: [CallbackQueryHandler(wizard_pe_sell, pattern=f"^{_CB_LEG}:")],
            WIZARD_PE_ATO_STRIKE: [
                CallbackQueryHandler(wizard_pe_ato_strike, pattern=f"^{_CB_ATO_STR}:")
            ],
            WIZARD_PE_ATO_STRIKE_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_pe_ato_strike_custom)
            ],
            WIZARD_CE_INTENT: [CallbackQueryHandler(wizard_ce_intent, pattern=f"^{_CB_SIDE}:ce:")],
            WIZARD_CE_BUY: [CallbackQueryHandler(wizard_ce_buy, pattern=f"^{_CB_LEG}:")],
            WIZARD_CE_SELL: [CallbackQueryHandler(wizard_ce_sell, pattern=f"^{_CB_LEG}:")],
            WIZARD_CE_ATO_STRIKE: [
                CallbackQueryHandler(wizard_ce_ato_strike, pattern=f"^{_CB_ATO_STR}:")
            ],
            WIZARD_CE_ATO_STRIKE_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_ce_ato_strike_custom)
            ],
            WIZARD_CE_ENTRY_MODE: [
                CallbackQueryHandler(wizard_buffer_mode, pattern=f"^{_CB_BUF_MODE}:"),
                CallbackQueryHandler(wizard_buffer_predefined, pattern=f"^{_CB_BUF}:"),
            ],
            WIZARD_CE_ENTRY_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_buffer_custom_text)
            ],
            WIZARD_PE_ENTRY_MODE: [
                CallbackQueryHandler(wizard_buffer_mode, pattern=f"^{_CB_BUF_MODE}:"),
                CallbackQueryHandler(wizard_buffer_predefined, pattern=f"^{_CB_BUF}:"),
            ],
            WIZARD_PE_ENTRY_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_buffer_custom_text)
            ],
            WIZARD_CE_EXIT_MODE: [
                CallbackQueryHandler(wizard_buffer_mode, pattern=f"^{_CB_BUF_MODE}:"),
                CallbackQueryHandler(wizard_buffer_predefined, pattern=f"^{_CB_BUF}:"),
            ],
            WIZARD_CE_EXIT_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_buffer_custom_text)
            ],
            WIZARD_PE_EXIT_MODE: [
                CallbackQueryHandler(wizard_buffer_mode, pattern=f"^{_CB_BUF_MODE}:"),
                CallbackQueryHandler(wizard_buffer_predefined, pattern=f"^{_CB_BUF}:"),
            ],
            WIZARD_PE_EXIT_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_buffer_custom_text)
            ],
            WIZARD_POLL_INTERVAL: [
                CallbackQueryHandler(wizard_poll_interval, pattern=f"^{_CB_POLL}:")
            ],
            WIZARD_CONFIRM: [CallbackQueryHandler(b.wizard_confirm, pattern=f"^{_CB_CONF}:")],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, b.wizard_timeout)],
        },
        fallbacks=[
            CommandHandler("cancel", b._wizard_cancel),
            CommandHandler("register", b.wizard_entry),
            CallbackQueryHandler(
                b.wizard_entry_menu, pattern=f"^{b._CB_MENU}:register$"
            ),
        ],
        conversation_timeout=timeout,
    )
