"""KAVACH ATO Configuration (Quick Tune) — buffers-only mid-session patch (Q83–Q98)."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, cast

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update


def _btn(text: str, callback_data: str, *, style: str | None = None) -> InlineKeyboardButton:
    """Inline button with optional Telegram style: primary|success|danger."""
    kwargs: dict[str, Any] = {"text": text, "callback_data": callback_data}
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)

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
    buffer_display,
    legacy_int_from_buffer,
    normalize_buffer_field,
    serialize_buffer_field,
)
from core.buffer_config.levels import (
    format_buffer_with_level,
    parse_and_validate_user_buffer_or_level,
)
logger = logging.getLogger("batman.kavach2.ato_tune")

TUNE_CONVERSATION_NAME = "kavach2_ato_tune"

(
    TUNE_SIDE,
    TUNE_BUF_MODE,
    TUNE_BUF_CUSTOM,
    TUNE_CONFIRM,
) = range(4)

_CB_ATC = "atc"
_CB_SIDE = f"{_CB_ATC}_side"
_CB_BUF = f"{_CB_ATC}_buf"
_CB_CONF = f"{_CB_ATC}_conf"

# UI targets (entry → exit per side; CE then PE when both — Q94 C / Q97 A)
_TARGET_KEYS = {
    "ce_entry": ("ce_entry_buffer", "ce_entry_buffer_points", "CE entry"),
    "ce_exit": ("ce_retrace_buffer", "ce_retrace_points", "CE exit"),
    "pe_entry": ("pe_entry_buffer", "pe_entry_buffer_points", "PE entry"),
    "pe_exit": ("pe_retrace_buffer", "pe_retrace_points", "PE exit"),
}

_ATC_USER_KEYS = (
    "atc_sides",
    "atc_queue",
    "atc_idx",
    "atc_baseline",
    "atc_pending",
    "atc_custom_target",
    "atc_holding",
)


def _bot():
    import bat_telegram.bots.kavach2.bot as bot_mod

    return bot_mod


def _ud(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return cast(dict[str, Any], context.user_data)


def _clear_tune_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    ud = _ud(context)
    for key in list(ud.keys()):
        if isinstance(key, str) and key.startswith("atc_"):
            ud.pop(key, None)


def _predefined_lists(context: ContextTypes.DEFAULT_TYPE) -> tuple[list[int], list[int]]:
    """Deprecated — predefined point grids removed (NIFTY levels only)."""
    del context
    return [], []


def _side_picker_keyboard() -> InlineKeyboardMarkup:
    """Q92 C — CE only | PE only | both | Cancel."""
    return InlineKeyboardMarkup(
        [
            [
                _btn("🔺 CE only", f"{_CB_SIDE}:ce", style="primary"),
                _btn("🔻 PE only", f"{_CB_SIDE}:pe", style="primary"),
            ],
            [_btn("🔀 Both CE & PE", f"{_CB_SIDE}:both", style="success")],
            [_btn("❌ Cancel", f"{_CB_SIDE}:cancel", style="danger")],
        ]
    )


def _buffer_step_keyboard(target: str) -> InlineKeyboardMarkup:
    """Keep current NIFTY level, or enter a new one."""
    return InlineKeyboardMarkup(
        [
            [_btn("Keep current", f"{_CB_BUF}:{target}:keep", style="primary")],
            [
                _btn("Enter NIFTY level", f"{_CB_BUF}:{target}:custom", style="primary")
            ],
            [_btn("❌ Cancel", f"{_CB_BUF}:{target}:cancel", style="danger")],
        ]
    )


def _predefined_buffer_keyboard(target: str, options: list[int]) -> InlineKeyboardMarkup:
    """Deprecated stub — predefined point pickers removed."""
    del options
    return InlineKeyboardMarkup(
        [
            [_btn("⬅️ Back", f"{_CB_BUF}:{target}:back", style="primary")],
            [_btn("❌ Cancel", f"{_CB_BUF}:{target}:cancel", style="danger")],
        ]
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                _btn("✅ Apply", f"{_CB_CONF}:apply", style="success"),
                _btn("❌ Cancel", f"{_CB_CONF}:cancel", style="danger"),
            ]
        ]
    )


def _queue_for_sides(sides: str) -> list[str]:
    if sides == "ce":
        return ["ce_entry", "ce_exit"]
    if sides == "pe":
        return ["pe_entry", "pe_exit"]
    return ["ce_entry", "ce_exit", "pe_entry", "pe_exit"]


def _load_baseline_from_deployment(dep: dict[str, Any]) -> dict[str, Any]:
    ato = dep.get("ato") or {}
    legacy_retrace = dep.get("retrace_points", 5)
    return {
        "ce_entry": ato.get("ce_entry_buffer", ato.get("ce_entry_buffer_points", 0)),
        "ce_exit": ato.get(
            "ce_retrace_buffer", ato.get("ce_retrace_points", legacy_retrace)
        ),
        "pe_entry": ato.get("pe_entry_buffer", ato.get("pe_entry_buffer_points", 0)),
        "pe_exit": ato.get(
            "pe_retrace_buffer", ato.get("pe_retrace_points", legacy_retrace)
        ),
    }


def _holding_flags(state: Any) -> dict[str, bool]:
    if not state:
        return {"ce": False, "pe": False}
    return {
        "ce": bool(state.get("ato.ce_triggered", False)),
        "pe": bool(state.get("ato.pe_triggered", False)),
    }


def _current_target(ud: dict[str, Any]) -> str | None:
    queue = ud.get("atc_queue") or []
    idx = int(ud.get("atc_idx", 0))
    if 0 <= idx < len(queue):
        return str(queue[idx])
    return None


def _sell_strikes_from_context(context: ContextTypes.DEFAULT_TYPE) -> dict[str, int | None]:
    """PE/CE sell strikes from armed deployment (for NIFTY level conversion)."""
    b = _bot()
    path = b._find_active_deployment()
    out: dict[str, int | None] = {"CE": None, "PE": None}
    if path is None:
        return out
    try:
        import json

        with open(path, encoding="utf-8") as fh:
            dep = json.load(fh)
        positions = dep.get("positions") or {}
        for side, key in (("CE", "ce_sell"), ("PE", "pe_sell")):
            leg = positions.get(key)
            if isinstance(leg, dict) and leg.get("strike") is not None:
                out[side] = int(leg["strike"])
    except Exception:
        pass
    return out


def _target_side_kind(target: str) -> tuple[str, str]:
    side = "CE" if target.startswith("ce") else "PE"
    kind = "entry" if "entry" in target else "exit"
    return side, kind


def _buffer_step_text(context: ContextTypes.DEFAULT_TYPE, target: str) -> str:
    b = _bot()
    ud = _ud(context)
    baseline = ud.get("atc_baseline") or {}
    pending = ud.get("atc_pending") or {}
    queue = ud.get("atc_queue") or []
    idx = int(ud.get("atc_idx", 0)) + 1
    total = len(queue)
    label = _TARGET_KEYS[target][2]
    cur = pending.get(target, baseline.get(target, 0))
    side, kind = _target_side_kind(target)
    sell = (_sell_strikes_from_context(context) or {}).get(side)
    cur_disp = b._md2(
        format_buffer_with_level(
            normalize_buffer_field(cur), side=side, kind=kind, sell_strike=sell
        )
    )
    sell_part = f"Sell strike: `{sell:,}`\n\n" if sell is not None else "\n"
    return (
        f"*Buffer Manager* — step {b._md2(str(idx))} of {b._md2(str(total))}\n\n"
        f"*{b._md2(label)}*\n"
        f"Current: *{cur_disp}*\n"
        f"{sell_part}"
        f"Keep the current NIFTY level, or enter a new one\\."
    )


async def _not_armed_reply(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Q98 B — Register first."""
    b = _bot()
    await b._reply_md2(
        message,
        "⚠️ No active deployment\\.\n\n"
        "Register first — tap *Register* or send `/register`\\.",
        reply_markup=b._main_menu_keyboard(),
    )
    return ConversationHandler.END


# Trailing invisible braille-blank padding (U+2800) on the copy line keeps the
# bubble at its original width without adding extra vertical height.
_SIDE_PICKER_PROMPT = (
    "*Buffer Manager*\n\n"
    "Select side :" + "\u2800" * 40
)


async def _start_side_picker(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    _clear_tune_data(context)
    await b._reply_md2(message, _SIDE_PICKER_PROMPT, reply_markup=_side_picker_keyboard())
    return TUNE_SIDE


async def tune_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Command `/ato_tune` entry (Q90 C)."""
    b = _bot()
    message = b._require_message(update)
    if not b._find_active_deployment():
        return await _not_armed_reply(message, context)
    return await _start_side_picker(message, context)


async def tune_entry_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menu / status button entry (Q90 C / Q91 A)."""
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    message = query.message
    if message is None:
        return ConversationHandler.END
    if not b._find_active_deployment():
        return await _not_armed_reply(message, context)
    await b._wizard_edit_step(
        context,
        query,
        _SIDE_PICKER_PROMPT,
        reply_markup=_side_picker_keyboard(),
    )
    _clear_tune_data(context)
    return TUNE_SIDE


async def tune_side_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    action = (query.data or "").split(":")[-1]
    if action == "cancel":
        return await _cancel_tune(query, context)

    dep_path = b._find_active_deployment()
    if not dep_path:
        return await _not_armed_reply(query.message, context)

    import json

    with open(dep_path, encoding="utf-8") as fh:
        dep = json.load(fh)

    ud = _ud(context)
    ud["atc_sides"] = action
    ud["atc_queue"] = _queue_for_sides(action)
    ud["atc_idx"] = 0
    ud["atc_baseline"] = _load_baseline_from_deployment(dep)
    ud["atc_pending"] = dict(ud["atc_baseline"])
    ud["atc_holding"] = _holding_flags(context.bot_data.get("state"))
    return await _ask_buffer_step(query, context)


async def _ask_buffer_step(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    target = _current_target(_ud(context))
    if target is None:
        return await _show_confirm(query, context)
    await b._wizard_edit_step(
        context,
        query,
        _buffer_step_text(context, target),
        reply_markup=_buffer_step_keyboard(target),
    )
    return TUNE_BUF_MODE


async def _ask_buffer_step_message(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    target = _current_target(_ud(context))
    if target is None:
        return await _show_confirm_message(message, context)
    await b._reply_md2(
        message,
        _buffer_step_text(context, target),
        reply_markup=_buffer_step_keyboard(target),
    )
    return TUNE_BUF_MODE


async def tune_buffer_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    parts = (query.data or "").split(":")
    # atc_buf:ce_entry:keep | custom | cancel | back
    target = parts[1] if len(parts) > 1 else ""
    action = parts[2] if len(parts) > 2 else ""
    ud = _ud(context)

    if action == "cancel":
        return await _cancel_tune(query, context)
    if action == "back":
        return await _ask_buffer_step(query, context)
    if action == "keep":
        ud["atc_idx"] = int(ud.get("atc_idx", 0)) + 1
        return await _ask_buffer_step(query, context)
    if action in {"custom", "level", "pred"}:
        # "pred" redirected: predefined points removed — NIFTY level entry only.
        ud["atc_custom_target"] = target
        side_label = _TARGET_KEYS[target][2]
        side, kind = _target_side_kind(target)
        sell = (_sell_strikes_from_context(context) or {}).get(side)
        sell_hint = f" \\(sell `{sell:,}`\\)" if sell is not None else ""
        kind_hint = "fire" if kind == "entry" else "retrace exit"
        await b._wizard_edit_step(
            context,
            query,
            f"Enter *{b._md2(side_label)}* NIFTY level where ATO should "
            f"{b._md2(kind_hint)}{sell_hint}\\.\n\n"
            f"Example: `24160`",
        )
        return TUNE_BUF_CUSTOM
    if action == "v":
        # Legacy predefined-point callback from old keyboards — ignore.
        await b._wizard_edit_step(
            context,
            query,
            "Predefined points are removed\\. Enter a *NIFTY level* instead\\.",
            reply_markup=_buffer_step_keyboard(target),
        )
        return TUNE_BUF_MODE

    return TUNE_BUF_MODE


async def tune_buffer_custom_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    message = b._require_message(update)
    ud = _ud(context)
    target = str(ud.get("atc_custom_target", "ce_entry"))
    side, kind = _target_side_kind(target)
    sell = (_sell_strikes_from_context(context) or {}).get(side)
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
        return TUNE_BUF_CUSTOM
    pending = ud.setdefault("atc_pending", {})
    pending[target] = serialize_buffer_field(value, BufferKind.CUSTOM)
    if sell is not None and value is not None:
        shown = format_buffer_with_level(value, side=side, kind=kind, sell_strike=sell)
        await message.reply_text(f"✅ Stored as {shown}")
    ud["atc_idx"] = int(ud.get("atc_idx", 0)) + 1
    return await _ask_buffer_step_message(message, context)


def _summary_and_warnings(context: ContextTypes.DEFAULT_TYPE) -> str:
    b = _bot()
    ud = _ud(context)
    baseline = ud.get("atc_baseline") or {}
    pending = ud.get("atc_pending") or {}
    holding = ud.get("atc_holding") or {}
    queue = ud.get("atc_queue") or []

    lines = ["*Buffer Manager — confirm*\n"]
    changed = False
    strikes = _sell_strikes_from_context(context)
    for target in queue:
        old = baseline.get(target, 0)
        new = pending.get(target, old)
        old_n = normalize_buffer_field(old)
        new_n = normalize_buffer_field(new)
        label = _TARGET_KEYS[target][2]
        side, kind = _target_side_kind(target)
        sell = strikes.get(side)
        old_disp = format_buffer_with_level(old_n, side=side, kind=kind, sell_strike=sell)
        new_disp = format_buffer_with_level(new_n, side=side, kind=kind, sell_strike=sell)
        if old_n == new_n:
            lines.append(
                f"• {b._md2(label)}: *{b._md2(old_disp)}* \\(unchanged\\)"
            )
        else:
            changed = True
            lines.append(
                f"• {b._md2(label)}: *{b._md2(old_disp)}* → "
                f"*{b._md2(new_disp)}*"
            )

    warnings: list[str] = []
    if not changed:
        warnings.append("No values changed — Apply will keep current NIFTY levels\\.")
    for side, flag in (("ce", holding.get("ce")), ("pe", holding.get("pe"))):
        if not flag:
            continue
        entry_t = f"{side}_entry"
        exit_t = f"{side}_exit"
        if entry_t in queue and normalize_buffer_field(
            pending.get(entry_t)
        ) != normalize_buffer_field(baseline.get(entry_t)):
            warnings.append(
                f"{side.upper()} holding: entry NIFTY level change applies to *next* cycle "
                f"after retrace \\(stay holding now\\)\\."
            )
        if exit_t in queue and normalize_buffer_field(
            pending.get(exit_t)
        ) != normalize_buffer_field(baseline.get(exit_t)):
            warnings.append(
                f"{side.upper()} holding: exit NIFTY level applies on *next tick*\\."
            )
    warnings.append("Lots / protect strikes are *not* changed by Buffer Manager\\.")

    lines.append("\n*Warnings*")
    for w in warnings:
        lines.append(f"⚠️ {w}")
    lines.append("\nApply patch to the armed deployment\\?")
    return "\n".join(lines)


async def _show_confirm(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    await b._wizard_edit_step(
        context,
        query,
        _summary_and_warnings(context),
        reply_markup=_confirm_keyboard(),
    )
    return TUNE_CONFIRM


async def _show_confirm_message(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    await b._reply_md2(
        message,
        _summary_and_warnings(context),
        reply_markup=_confirm_keyboard(),
    )
    return TUNE_CONFIRM


async def tune_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    query = b._require_query(update)
    await b._safe_answer_callback(query)
    action = (query.data or "").split(":")[-1]
    if action == "cancel":
        return await _cancel_tune(query, context)

    ud = _ud(context)
    baseline = ud.get("atc_baseline") or {}
    pending = ud.get("atc_pending") or {}
    queue = ud.get("atc_queue") or []
    patches: dict[str, Any] = {}
    for target in queue:
        new = pending.get(target, baseline.get(target))
        if normalize_buffer_field(new) != normalize_buffer_field(baseline.get(target)):
            patches[target] = new
        else:
            # Keep typed form even if unchanged when operator touches side — only write diffs
            pass

    if not patches:
        # Nothing to write — still OK
        await b._wizard_edit_step(
            context,
            query,
            "✅ No NIFTY level changes to apply\\.",
            reply_markup=b._main_menu_keyboard(),
        )
        _clear_tune_data(context)
        return ConversationHandler.END

    try:
        path = b.apply_ato_buffer_patch(
            patches,
            state=context.bot_data.get("state"),
        )
    except Exception as exc:
        logger.exception("ATO tune apply failed")
        await b._wizard_edit_step(
            context,
            query,
            f"❌ Apply failed: {b._md2(str(exc))}",
            reply_markup=b._main_menu_keyboard(),
        )
        _clear_tune_data(context)
        return ConversationHandler.END

    b._append_log("ato_tune_applied", patches={k: buffer_display(v) for k, v in patches.items()})
    strikes = _sell_strikes_from_context(context)
    lines = ["✅ *Buffer Manager applied*\n"]
    for target, raw in patches.items():
        side, kind = _target_side_kind(target)
        sell = strikes.get(side)
        disp = format_buffer_with_level(
            normalize_buffer_field(raw), side=side, kind=kind, sell_strike=sell
        )
        lines.append(f"• {b._md2(_TARGET_KEYS[target][2])}: *{b._md2(disp)}*")
    lines.append(f"\nDeployment: `{b._md2_code(path.name)}`")
    await b._wizard_edit_step(
        context,
        query,
        "\n".join(lines),
        reply_markup=b._main_menu_keyboard(),
    )
    _clear_tune_data(context)
    return ConversationHandler.END


async def _cancel_tune(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    _clear_tune_data(context)
    b._append_log("ato_tune_cancelled")
    await b._wizard_edit_step(
        context,
        query,
        "❌ Buffer Manager cancelled\\.",
        reply_markup=b._main_menu_keyboard(),
    )
    return ConversationHandler.END


async def tune_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    b = _bot()
    _clear_tune_data(context)
    message = update.effective_message
    if message is not None:
        await b._reply_md2(
            message,
            "❌ Buffer Manager cancelled\\.",
            reply_markup=b._main_menu_keyboard(),
        )
    return ConversationHandler.END


async def tune_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    del update
    b = _bot()
    _clear_tune_data(context)
    b._append_log("ato_tune_timeout")
    return ConversationHandler.END


def build_ato_tune_handler(timeout: int) -> ConversationHandler:
    b = _bot()
    return ConversationHandler(
        allow_reentry=True,
        name=TUNE_CONVERSATION_NAME,
        entry_points=[
            CommandHandler("ato_tune", tune_entry),
            CallbackQueryHandler(tune_entry_menu, pattern=f"^{b._CB_MENU}:ato_tune$"),
            CallbackQueryHandler(tune_entry_menu, pattern=f"^{_CB_ATC}:start$"),
        ],
        states={
            TUNE_SIDE: [CallbackQueryHandler(tune_side_pick, pattern=f"^{_CB_SIDE}:")],
            TUNE_BUF_MODE: [CallbackQueryHandler(tune_buffer_action, pattern=f"^{_CB_BUF}:")],
            TUNE_BUF_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, tune_buffer_custom_text)
            ],
            TUNE_CONFIRM: [CallbackQueryHandler(tune_confirm, pattern=f"^{_CB_CONF}:")],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, tune_timeout)],
        },
        fallbacks=[
            CommandHandler("cancel", tune_cancel_command),
            CommandHandler("ato_tune", tune_entry),
            CallbackQueryHandler(tune_entry_menu, pattern=f"^{b._CB_MENU}:ato_tune$"),
        ],
        conversation_timeout=timeout,
    )


# Re-export helpers for tests
__all__ = [
    "TUNE_SIDE",
    "TUNE_BUF_MODE",
    "TUNE_BUF_CUSTOM",
    "TUNE_CONFIRM",
    "TUNE_CONVERSATION_NAME",
    "_CB_ATC",
    "_CB_SIDE",
    "_CB_BUF",
    "_CB_CONF",
    "build_ato_tune_handler",
    "tune_entry",
    "tune_entry_menu",
    "tune_side_pick",
    "tune_buffer_action",
    "tune_buffer_custom_text",
    "tune_confirm",
    "apply_patches_dict",
    "_queue_for_sides",
    "_load_baseline_from_deployment",
    "_summary_and_warnings",
]


def apply_patches_dict(
    ato: dict[str, Any],
    dep: dict[str, Any],
    patches: dict[str, Any],
) -> None:
    """Mutate deployment `ato` (+ top-level retrace_points) from target→raw patches."""
    for target, raw in patches.items():
        typed_key, legacy_key, _ = _TARGET_KEYS[target]
        dec = normalize_buffer_field(raw)
        if isinstance(raw, dict) and raw.get("type"):
            typed = raw
        else:
            typed = serialize_buffer_field(dec, BufferKind.CUSTOM)
        ato[typed_key] = typed
        ato[legacy_key] = legacy_int_from_buffer(typed)
        if target == "ce_exit":
            dep["retrace_points"] = legacy_int_from_buffer(typed, default=5)
            ato["retrace_points"] = dep["retrace_points"]
