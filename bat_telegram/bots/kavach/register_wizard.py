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
    parse_and_validate_user_buffer,
    serialize_buffer_field,
)
from core.position_scope import (
    auto_protect_strike,
    filter_positions_by_direction,
    filter_positions_by_side,
    parse_and_validate_ato_lots,
    parse_and_validate_protect_strike,
    qty_to_lots,
    resolve_nifty_lot_size,
    scale_side_flexible,
    side_lots_selection,
    suggested_ato_lots,
)
from core.positions import build_ato_protect_symbol
from core.wizard_plan import (
    question_index,
    rebuild_wizard_plan,
    section_label,
    step_meta,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

logger = logging.getLogger("batman.kavach.wizard")

WIZARD_CONVERSATION_NAME = "kavach_register"

# ── Conversation states ───────────────────────────────────────────────────────
(
    WIZARD_ORDER_MODE,
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
) = range(27)

_CB_PRE = "wiz_pre"
_CB_ORDER_MODE = "wiz_omode"
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
    section, label = step_meta(step_id)
    sec = section_label(section)
    return (
        f"*Question {b._md2(str(idx))} of {b._md2(str(total))} — "
        f"{b._md2(sec)} — {b._md2(label)}*\n\n{body}"
    )


def _store_protect_strike(wiz: dict[str, Any], side: str, strike: int, mode: str) -> None:
    side_l = side.lower()
    sell = wiz[f"{side_l}_sell"]
    opt = side.upper()
    wiz[f"{side_l}_protect_strike"] = int(strike)
    wiz[f"{side_l}_protect_strike_mode"] = mode
    wiz[f"{side_l}_protect_symbol"] = build_ato_protect_symbol(
        str(sell["symbol"]), int(strike), opt
    )


def _ato_strike_keyboard(
    side: str,
    auto_strike: int,
    sell_strike: int,
    *,
    preset_offsets: list[int] | None = None,
) -> InlineKeyboardMarkup:
    opt = side.upper()
    side_l = side.lower()
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                f"Auto: {auto_strike:,} {opt}",
                callback_data=f"{_CB_ATO_STR}:{side_l}:auto",
            )
        ]
    ]
    for offset in preset_offsets or []:
        off = int(offset)
        if opt == "CE":
            strike = int(sell_strike) + off
            label = f"+{off:,} → {strike:,} {opt}"
        else:
            strike = int(sell_strike) - off
            label = f"−{off:,} → {strike:,} {opt}"
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{_CB_ATO_STR}:{side_l}:preset:{off}",
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "Enter custom strike",
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
    return InlineKeyboardMarkup(rows)


def _strike_presets_for_side(context: ContextTypes.DEFAULT_TYPE, side: str) -> list[int]:
    from core.ato_operator_config import ato_operator_settings

    op = ato_operator_settings(context.bot_data.get("params"))
    if str(side).upper() == "CE":
        return [int(x) for x in op.get("strike_presets_ce", [500, 1000])]
    return [int(x) for x in op.get("strike_presets_pe", [100, 500])]


def _apply_ato_strike_action(
    wiz: dict,
    side: str,
    action: str,
    parts: list[str],
    *,
    ato_step: int,
) -> tuple[int, str] | None:
    """Return (strike, mode) or None if action not a strike selection."""
    side_u = side.upper()
    sell_key = "pe_sell" if side_u == "PE" else "ce_sell"
    sell_strike = int(wiz[sell_key]["strike"])
    if action == "auto":
        return auto_protect_strike(sell_strike, side_u, ato_step=ato_step), "AUTO"
    if action == "preset" and len(parts) >= 2:
        offset = int(parts[-1])
        if side_u == "CE":
            return sell_strike + offset, "PRESET"
        return sell_strike - offset, "PRESET"
    return None


def _parse_ato_strike_callback(data: str) -> tuple[str, str, int | None]:
    """Parse wiz_astr:{side}:{action} or wiz_astr:{side}:preset:{offset}."""
    parts = (data or "").split(":")
    side = parts[1] if len(parts) > 1 else ""
    if len(parts) >= 4 and parts[2] == "preset":
        return side, "preset", int(parts[3])
    action = parts[2] if len(parts) > 2 else ""
    return side, action, None


def _ato_strike_prompt_body(
    side: str, sell_strike: int, auto_strike: int, *, ato_step: int
) -> str:
    b = _bot()
    side_esc = b._md2(side.upper())
    op = "+" if side.upper() == "CE" else "−"
    return (
        f"{side_esc} SELL strike: `{sell_strike:,}`\n"
        f"Auto ATO: `{auto_strike:,} {side.upper()}` "
        f"\\(sell {op} {ato_step}\\)"
    )


def _bot():
    import bat_telegram.bots.kavach.bot as bot_mod

    return bot_mod


def _wiz(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return cast(dict[str, Any], context.user_data)


def _predefined_lists(context: ContextTypes.DEFAULT_TYPE) -> tuple[list[int], list[int]]:
    params = context.bot_data.get("params") or {}
    ato = params.get("ato", {})
    entry = ato.get(
        "predefined_entry_buffers",
        [1, 5, 10, 20, 35, 50],
    )
    exit_ = ato.get(
        "predefined_exit_buffers",
        [1, 5, 10, 20, 35, 50],
    )
    return [int(v) for v in entry], [int(v) for v in exit_]


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
    b = _bot()
    side_esc = b._md2(side)
    body = (
        f"Managed Batman lots: *{b._md2(str(managed_lots))}*\n"
        f"Suggested: *{b._md2(str(suggested))}* lots \\(same as managed BUY\\)\n\n"
        f"Type how many ATO lots to deploy when {side_esc} breaches\\.\n"
        f"`0` = monitor only, no ATO order\\.\n\n"
        f"Enter a whole number ≥ 0\\."
    )
    step_id = "pe_ato_lots" if side.upper() == "PE" else "ce_ato_lots"
    return _qheader(context, step_id, body)


def _lots_prompt_md(
    context: ContextTypes.DEFAULT_TYPE,
    side: str,
    buy_qty: int,
    sell_qty: int,
    lot_size: int,
) -> str:
    b = _bot()
    max_l, buy_l, sell_l, lot_size = side_lots_selection(buy_qty, sell_qty, lot_size=lot_size)
    body = (
        f"BUY `{buy_qty}` qty \\({buy_l} lots\\) · SELL `{sell_qty}` qty \\({sell_l} lots\\)\n"
        f"NIFTY lot size {lot_size} · max *{max_l}* lots:"
    )
    step_id = "pe_lots" if side.upper() == "PE" else "ce_lots"
    return _qheader(context, step_id, body)


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
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Predefined", callback_data=f"{_CB_BUF_MODE}:{target}:pred"),
                InlineKeyboardButton("Custom", callback_data=f"{_CB_BUF_MODE}:{target}:custom"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_BUF_MODE}:{target}:cancel")],
        ]
    )


def _predefined_buffer_keyboard(target: str, options: list[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for v in options:
        row.append(InlineKeyboardButton(f"{v} pts", callback_data=f"{_CB_BUF}:{target}:{v}"))
        if len(row) >= 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"{_CB_BUF}:cancel")])
    return InlineKeyboardMarkup(rows)


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
    body = f"Select *{side} {_buffer_kind_label(target)} buffer* mode:"
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


async def wizard_pe_intent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    data = query.data or ""
    if data.endswith(":cancel"):
        return await _cancel_wizard(query, context)
    wiz = _wiz(context)
    if data.endswith(":skip"):
        wiz["pe_enabled"] = False
        rebuild_wizard_plan(wiz)
        return await _goto_ce_intent(query, context)
    wiz["pe_enabled"] = True
    rebuild_wizard_plan(wiz)
    all_pos = cast(list[dict], wiz["wiz_positions"])
    long_pe = filter_positions_by_direction(filter_positions_by_side(all_pos, "PE"), "LONG")
    lot_size = _lot_size(context)
    body = "Select your *PE BUY* leg \\(LONG PE\\):"
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "pe_buy", body),
        reply_markup=_positions_keyboard(long_pe, lot_size),
    )
    wiz["_pe_pick_pool"] = long_pe
    return WIZARD_PE_BUY


async def _goto_ce_intent(query, context) -> int:
    b = _bot()
    body = "Enable *CE side* coverage?"
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "ce_intent", body),
        reply_markup=ce_intent_keyboard(),
    )
    return WIZARD_CE_INTENT


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
    body = f"{header}\n\nSelect your *PE SELL* leg \\(SHORT PE\\):"
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
    lot_size = _lot_size(context)
    buy_qty = abs(int(wiz["pe_buy"]["qty"]))
    sell_qty = abs(int(pe_sell["qty"]))
    max_l, _, _, lot_size = side_lots_selection(buy_qty, sell_qty, lot_size=lot_size)
    await b._wizard_edit_step(
        context,
        query,
        _lots_prompt_md(context, "PE", buy_qty, sell_qty, lot_size),
        reply_markup=_lots_keyboard("pe", max_l),
    )
    wiz["_pe_max_lots"] = max_l
    return WIZARD_PE_LOTS


async def wizard_pe_lots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    if query.data == f"{_CB_LOTS}:cancel":
        return await _cancel_wizard(query, context)
    parts = (query.data or "").split(":")
    lots = wiz["_pe_max_lots"] if parts[-1] == "all" else int(parts[-1])
    lot_size = _lot_size(context)
    buy, sell = scale_side_flexible(wiz["pe_buy"], wiz["pe_sell"], lots, lot_size=lot_size)
    wiz["pe_buy"] = buy
    wiz["pe_sell"] = sell
    wiz["pe_managed_lots"] = lots
    return await _ask_pe_ato_lots(query, context)


async def _ask_pe_ato_lots(query, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    lot_size = _lot_size(context)
    managed = int(wiz["pe_managed_lots"])
    suggested = suggested_ato_lots(managed, abs(int(wiz["pe_buy"]["qty"])), lot_size=lot_size)
    wiz["_pe_ato_suggested"] = suggested
    await b._wizard_edit_step(
        context, query, _ato_lots_prompt_md(context, "PE", managed, suggested)
    )
    return WIZARD_PE_ATO_LOTS


async def wizard_pe_ato_lots_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    wiz = _wiz(context)
    value, err = parse_and_validate_ato_lots(message.text or "")
    if err:
        await message.reply_text(f"❌ {err}")
        return WIZARD_PE_ATO_LOTS
    wiz["pe_ato_lots"] = value
    return await _ask_pe_ato_strike_message(message, context)


async def _ask_pe_ato_strike(query, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    step = _ato_step(context)
    sell_strike = int(wiz["pe_sell"]["strike"])
    auto_strike = auto_protect_strike(sell_strike, "PE", ato_step=step)
    wiz["_pe_auto_protect_strike"] = auto_strike
    body = _ato_strike_prompt_body("PE", sell_strike, auto_strike, ato_step=step)
    presets = _strike_presets_for_side(context, "PE")
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "pe_ato_strike", body),
        reply_markup=_ato_strike_keyboard("PE", auto_strike, sell_strike, preset_offsets=presets),
    )
    return WIZARD_PE_ATO_STRIKE


async def _ask_pe_ato_strike_message(message, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    step = _ato_step(context)
    sell_strike = int(wiz["pe_sell"]["strike"])
    auto_strike = auto_protect_strike(sell_strike, "PE", ato_step=step)
    wiz["_pe_auto_protect_strike"] = auto_strike
    body = _ato_strike_prompt_body("PE", sell_strike, auto_strike, ato_step=step)
    presets = _strike_presets_for_side(context, "PE")
    await b._reply_md2(
        message,
        _qheader(context, "pe_ato_strike", body),
        reply_markup=_ato_strike_keyboard("PE", auto_strike, sell_strike, preset_offsets=presets),
    )
    return WIZARD_PE_ATO_STRIKE


async def wizard_pe_ato_strike(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    _side, action, preset_off = _parse_ato_strike_callback(query.data or "")
    if action == "cancel":
        return await _cancel_wizard(query, context)
    if action == "custom":
        body = (
            "Enter *PE ATO protect strike*\\.\n"
            "Must be a whole number on the NIFTY grid \\(multiple of 50\\)\\.\n"
            "Example: 23500"
        )
        await b._wizard_edit_step(context, query, _qheader(context, "pe_ato_strike", body))
        return WIZARD_PE_ATO_STRIKE_CUSTOM
    step = _ato_step(context)
    if action == "auto":
        auto_strike = int(wiz.get("_pe_auto_protect_strike", 0))
        _store_protect_strike(wiz, "PE", auto_strike, "AUTO")
    elif action == "preset" and preset_off is not None:
        sell_strike = int(wiz["pe_sell"]["strike"])
        _store_protect_strike(wiz, "PE", sell_strike - preset_off, "PRESET")
    return await _ask_buffer_mode(query, context, "pe_entry")


async def wizard_pe_ato_strike_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    wiz = _wiz(context)
    value, err = parse_and_validate_protect_strike(message.text or "")
    if err:
        await message.reply_text(f"❌ {err}")
        return WIZARD_PE_ATO_STRIKE_CUSTOM
    _store_protect_strike(wiz, "PE", value, "CUSTOM")
    await b._reply_md2(
        message,
        _buffer_step_title(context, "pe_entry"),
        reply_markup=_buffer_mode_keyboard("pe_entry"),
    )
    return WIZARD_PE_ENTRY_MODE


async def _goto_ce_intent_message(message, context) -> int:
    b = _bot()
    body = "Enable *CE side* coverage?"
    await b._reply_md2(
        message,
        _qheader(context, "ce_intent", body),
        reply_markup=ce_intent_keyboard(),
    )
    return WIZARD_CE_INTENT


async def wizard_ce_intent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    if query.data.endswith(":cancel"):
        return await _cancel_wizard(query, context)
    if not wiz.get("pe_enabled") and query.data.endswith(":skip"):
        await b._wizard_edit_step(
            context,
            query,
            "⚠️ Select at least one side \\(PE or CE\\)\\.",
        )
        b._clear_wizard_data(context)
        return ConversationHandler.END
    if query.data.endswith(":skip"):
        wiz["ce_enabled"] = False
        rebuild_wizard_plan(wiz)
        return await _goto_poll(query, context)
    wiz["ce_enabled"] = True
    rebuild_wizard_plan(wiz)
    all_pos = cast(list[dict], wiz["wiz_positions"])
    long_ce = filter_positions_by_direction(filter_positions_by_side(all_pos, "CE"), "LONG")
    lot_size = _lot_size(context)
    body = "Select your *CE BUY* leg \\(LONG CE\\):"
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "ce_buy", body),
        reply_markup=_positions_keyboard(long_ce, lot_size),
    )
    wiz["_ce_pick_pool"] = long_ce
    return WIZARD_CE_BUY


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
    body = f"{header}\n\nSelect your *CE SELL* leg \\(SHORT CE\\):"
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
    lot_size = _lot_size(context)
    buy_qty = abs(int(wiz["ce_buy"]["qty"]))
    sell_qty = abs(int(ce_sell["qty"]))
    max_l, _, _, lot_size = side_lots_selection(buy_qty, sell_qty, lot_size=lot_size)
    await b._wizard_edit_step(
        context,
        query,
        _lots_prompt_md(context, "CE", buy_qty, sell_qty, lot_size),
        reply_markup=_lots_keyboard("ce", max_l),
    )
    wiz["_ce_max_lots"] = max_l
    return WIZARD_CE_LOTS


async def wizard_ce_lots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    if query.data == f"{_CB_LOTS}:cancel":
        return await _cancel_wizard(query, context)
    parts = (query.data or "").split(":")
    lots = wiz["_ce_max_lots"] if parts[-1] == "all" else int(parts[-1])
    lot_size = _lot_size(context)
    buy, sell = scale_side_flexible(wiz["ce_buy"], wiz["ce_sell"], lots, lot_size=lot_size)
    wiz["ce_buy"] = buy
    wiz["ce_sell"] = sell
    wiz["ce_managed_lots"] = lots
    return await _ask_ce_ato_lots(query, context)


async def _ask_ce_ato_lots(query, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    lot_size = _lot_size(context)
    managed = int(wiz["ce_managed_lots"])
    suggested = suggested_ato_lots(managed, abs(int(wiz["ce_buy"]["qty"])), lot_size=lot_size)
    wiz["_ce_ato_suggested"] = suggested
    await b._wizard_edit_step(
        context, query, _ato_lots_prompt_md(context, "CE", managed, suggested)
    )
    return WIZARD_CE_ATO_LOTS


async def wizard_ce_ato_lots_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    wiz = _wiz(context)
    value, err = parse_and_validate_ato_lots(message.text or "")
    if err:
        await message.reply_text(f"❌ {err}")
        return WIZARD_CE_ATO_LOTS
    wiz["ce_ato_lots"] = value
    return await _ask_ce_ato_strike_message(message, context)


async def _ask_ce_ato_strike(query, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    step = _ato_step(context)
    sell_strike = int(wiz["ce_sell"]["strike"])
    auto_strike = auto_protect_strike(sell_strike, "CE", ato_step=step)
    wiz["_ce_auto_protect_strike"] = auto_strike
    body = _ato_strike_prompt_body("CE", sell_strike, auto_strike, ato_step=step)
    presets = _strike_presets_for_side(context, "CE")
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "ce_ato_strike", body),
        reply_markup=_ato_strike_keyboard("CE", auto_strike, sell_strike, preset_offsets=presets),
    )
    return WIZARD_CE_ATO_STRIKE


async def _ask_ce_ato_strike_message(message, context) -> int:
    b = _bot()
    wiz = _wiz(context)
    step = _ato_step(context)
    sell_strike = int(wiz["ce_sell"]["strike"])
    auto_strike = auto_protect_strike(sell_strike, "CE", ato_step=step)
    wiz["_ce_auto_protect_strike"] = auto_strike
    body = _ato_strike_prompt_body("CE", sell_strike, auto_strike, ato_step=step)
    presets = _strike_presets_for_side(context, "CE")
    await b._reply_md2(
        message,
        _qheader(context, "ce_ato_strike", body),
        reply_markup=_ato_strike_keyboard("CE", auto_strike, sell_strike, preset_offsets=presets),
    )
    return WIZARD_CE_ATO_STRIKE


async def wizard_ce_ato_strike(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    _side, action, preset_off = _parse_ato_strike_callback(query.data or "")
    if action == "cancel":
        return await _cancel_wizard(query, context)
    if action == "custom":
        body = (
            "Enter *CE ATO protect strike*\\.\n"
            "Must be a whole number on the NIFTY grid \\(multiple of 50\\)\\.\n"
            "Example: 24100"
        )
        await b._wizard_edit_step(context, query, _qheader(context, "ce_ato_strike", body))
        return WIZARD_CE_ATO_STRIKE_CUSTOM
    if action == "auto":
        auto_strike = int(wiz.get("_ce_auto_protect_strike", 0))
        _store_protect_strike(wiz, "CE", auto_strike, "AUTO")
    elif action == "preset" and preset_off is not None:
        sell_strike = int(wiz["ce_sell"]["strike"])
        _store_protect_strike(wiz, "CE", sell_strike + preset_off, "PRESET")
    return await _ask_buffer_mode(query, context, "ce_entry")


async def wizard_ce_ato_strike_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    wiz = _wiz(context)
    value, err = parse_and_validate_protect_strike(message.text or "")
    if err:
        await message.reply_text(f"❌ {err}")
        return WIZARD_CE_ATO_STRIKE_CUSTOM
    _store_protect_strike(wiz, "CE", value, "CUSTOM")
    await b._reply_md2(
        message,
        _buffer_step_title(context, "ce_entry"),
        reply_markup=_buffer_mode_keyboard("ce_entry"),
    )
    return WIZARD_CE_ENTRY_MODE


async def _ask_buffer_mode(query, context, target: str) -> int:
    b = _bot()
    await b._wizard_edit_step(
        context,
        query,
        _buffer_step_title(context, target),
        reply_markup=_buffer_mode_keyboard(target),
    )
    return _mode_state_for_target(target)


async def wizard_buffer_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    parts = (query.data or "").split(":")
    target = _str_step_target(parts[1] if len(parts) > 1 else "")
    action = parts[2]
    if action == "cancel":
        return await _cancel_wizard(query, context)
    if action == "custom":
        wiz["_buf_custom_target"] = target
        side = "CE" if target.startswith("ce") else "PE"
        kind = "entry" if "entry" in target else "exit"
        await b._wizard_edit_step(
            context,
            query,
            f"Enter custom {side} {kind} buffer points \\(e\\.g\\. 1\\.5\\):",
        )
        return _custom_state_for_target(target)
    entry_opts, exit_opts = _predefined_lists(context)
    opts = entry_opts if "entry" in target else exit_opts
    await b._wizard_edit_step(
        context,
        query,
        "*Select predefined value:*",
        reply_markup=_predefined_buffer_keyboard(target, opts),
    )
    return _mode_state_for_target(target)


async def wizard_buffer_predefined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    if query.data == f"{_CB_BUF}:cancel":
        return await _cancel_wizard(query, context)
    parts = (query.data or "").split(":")
    target = _str_step_target(parts[1] if len(parts) > 1 else "")
    value = Decimal(parts[2])
    wiz = _wiz(context)
    wiz[_wiz_key_for_target(target)] = serialize_buffer_field(value, BufferKind.PREDEFINED)
    return await _advance_after_buffer(query, context, target)


async def wizard_buffer_custom_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    wiz = _wiz(context)
    target = str(wiz.get("_buf_custom_target", "ce_entry"))
    params = context.bot_data.get("params") or {}
    ato = params.get("ato", {})
    value, err = parse_and_validate_user_buffer(
        message.text or "",
        min_value=Decimal(str(ato.get("buffer_min", "0.1"))),
        max_value=Decimal(str(ato.get("buffer_max", "100"))),
    )
    if err:
        await message.reply_text(f"❌ {err}")
        return _custom_state_for_target(target)
    wiz[_wiz_key_for_target(target)] = serialize_buffer_field(value, BufferKind.CUSTOM)
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
            await b._reply_md2(
                message,
                _buffer_step_title(context, nxt),
                reply_markup=_buffer_mode_keyboard(nxt),
            )
            return _mode_state_for_target(nxt)
        return await _goto_ce_intent_message(message, context)
    nxt = _next_in_sequence(_CE_BUFFER_SEQUENCE, target)
    if nxt:
        await b._reply_md2(
            message,
            _buffer_step_title(context, nxt),
            reply_markup=_buffer_mode_keyboard(nxt),
        )
        return _mode_state_for_target(nxt)
    body = "Select *NIFTY LTP poll interval* for ATO monitoring:"
    await b._reply_md2(
        message,
        _qheader(context, "poll", body),
        reply_markup=b._poll_interval_keyboard(),
    )
    return WIZARD_POLL_INTERVAL


async def _goto_poll(query, context) -> int:
    b = _bot()
    body = "Select *NIFTY LTP poll interval* for ATO monitoring:"
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
    notes = []
    if not wiz.get("pe_enabled"):
        notes.append("_PE monitoring disabled \\(not registered\\)_")
    if not wiz.get("ce_enabled"):
        notes.append("_CE monitoring disabled \\(not registered\\)_")
    note = "\n".join(notes)
    body = f"Choose which side\\(s\\) to monitor for ATO breaches\\.\n{note}"
    await b._wizard_edit_step(
        context,
        query,
        _qheader(context, "ato_mon", body),
        reply_markup=_ato_monitor_keyboard(
            bool(wiz.get("pe_enabled")), bool(wiz.get("ce_enabled"))
        ),
    )
    return WIZARD_ATO_MON


async def wizard_ato_mon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    wiz = _wiz(context)
    if query.data == f"{_CB_ATO_MON}:cancel":
        return await _cancel_wizard(query, context)
    side = (query.data or "").split(":")[-1]
    wiz["wiz_ato_manage_sides"] = side
    b._wizard_seed_trading_calendar_defaults(wiz)
    _sync_wiz_selected(wiz)
    return await b._wizard_show_summary(query, context)



async def wizard_order_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """First /register question — Paper vs Live (does not change later questions)."""
    b = _bot()
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    raw = str(query.data or "")
    mode = "paper"
    if raw.endswith(":live"):
        mode = "live"
    elif raw.endswith(":paper"):
        mode = "paper"
    wiz = _wiz(context)
    wiz["order_mode"] = mode
    rebuild_wizard_plan(wiz)
    try:
        from core.money_audit import audit

        audit("register.order_mode", mode=mode)
    except Exception:
        pass
    logger.info("Register order_mode selected: %s", mode)
    try:
        from core.money_audit import audit

        audit("register.order_mode.ui", mode=mode, callback=raw[:80])
    except Exception:
        pass
    # Continue existing register pipeline (preamble / UAT / fetch legs)
    return await b._wizard_continue_after_order_mode(update, context)


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
            WIZARD_ORDER_MODE: [
                CallbackQueryHandler(wizard_order_mode, pattern=f"^{_CB_ORDER_MODE}:")
            ],
            WIZARD_PRE_CONFIRM: [
                CallbackQueryHandler(b.wizard_pre_confirm, pattern=f"^{_CB_PRE}:")
            ],
            WIZARD_PE_INTENT: [CallbackQueryHandler(wizard_pe_intent, pattern=f"^{_CB_SIDE}:pe:")],
            WIZARD_PE_BUY: [CallbackQueryHandler(wizard_pe_buy, pattern=f"^{_CB_LEG}:")],
            WIZARD_PE_SELL: [CallbackQueryHandler(wizard_pe_sell, pattern=f"^{_CB_LEG}:")],
            WIZARD_PE_LOTS: [CallbackQueryHandler(wizard_pe_lots, pattern=f"^{_CB_LOTS}:")],
            WIZARD_PE_ATO_LOTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_pe_ato_lots_text)
            ],
            WIZARD_PE_ATO_STRIKE: [
                CallbackQueryHandler(wizard_pe_ato_strike, pattern=f"^{_CB_ATO_STR}:")
            ],
            WIZARD_PE_ATO_STRIKE_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_pe_ato_strike_custom)
            ],
            WIZARD_CE_INTENT: [CallbackQueryHandler(wizard_ce_intent, pattern=f"^{_CB_SIDE}:ce:")],
            WIZARD_CE_BUY: [CallbackQueryHandler(wizard_ce_buy, pattern=f"^{_CB_LEG}:")],
            WIZARD_CE_SELL: [CallbackQueryHandler(wizard_ce_sell, pattern=f"^{_CB_LEG}:")],
            WIZARD_CE_LOTS: [CallbackQueryHandler(wizard_ce_lots, pattern=f"^{_CB_LOTS}:")],
            WIZARD_CE_ATO_LOTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_ce_ato_lots_text)
            ],
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
            WIZARD_ATO_MON: [CallbackQueryHandler(wizard_ato_mon, pattern=f"^{_CB_ATO_MON}:")],
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
