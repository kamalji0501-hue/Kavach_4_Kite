from __future__ import annotations

import logging
import time
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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

logger = logging.getLogger("batman.sanchalak")

_CB = "sanch"
_HELP = (
    "SANCHALAK -- Available Commands\n\n"
    "/start_all -- Authorize and start active runtime scope\n"
    "/stop_all -- Stop active runtime scope (confirm required, 60s timeout)\n"
    "/pause_bot <name> -- Pause a target bot/module\n"
    "/resume_bot <name> -- Resume a target bot/module\n"
    "/set_mode <mock|live> -- Set global mode (confirm required, 60s timeout)\n"
    "/status_all -- Consolidated status of bots/modules/mode"
)


def _require_message(update: Update) -> Message:
    message = update.message
    if message is None:
        raise ValueError("Telegram update is missing a message")
    return message


def _confirmation_timeout_seconds(app: Application) -> int:
    params = cast(dict[str, Any], app.bot_data.get("params", {}))
    raw = params.get("confirmation_timeout_seconds", 60)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 60
    return max(10, value)


def _state_get(state, key: str, default: Any = None) -> Any:
    if state is None:
        return default
    try:
        return state.get(key, default)
    except Exception:
        return default


def _state_set(state, key: str, value: Any) -> None:
    if state is None:
        return
    try:
        state.set(key, value)
    except Exception as exc:
        logger.warning("SANCHALAK state.set failed for %s: %s", key, exc)


def _mode_now(app: Application) -> str:
    state = app.bot_data.get("state")
    mode = str(_state_get(state, "control.runtime_mode", "mock") or "mock").lower()
    return mode if mode in {"mock", "live"} else "mock"


def _set_mode_for_all_apps(app: Application, mode: str) -> None:
    apps = cast(dict[str, Any], app.bot_data.get("apps", {}))
    for _, target_app in apps.items():
        target_app.bot_data["runtime_mode"] = mode


def _set_global_enabled(app: Application, enabled: bool) -> None:
    state = app.bot_data.get("state")
    _state_set(state, "control.global_enabled", bool(enabled))


def _paused_apps_map(state) -> dict[str, bool]:
    paused = _state_get(state, "control.paused_apps", {})
    if isinstance(paused, dict):
        return {str(k): bool(v) for k, v in paused.items()}
    return {}


def _save_paused_apps_map(state, mapping: dict[str, bool]) -> None:
    _state_set(state, "control.paused_apps", mapping)


def _module_names(app: Application) -> list[str]:
    modules = cast(dict[str, Any], app.bot_data.get("modules", {}))
    return sorted(modules.keys())


def _app_names(app: Application) -> list[str]:
    apps = cast(dict[str, Any], app.bot_data.get("apps", {}))
    return sorted(apps.keys())


def _active_pending_action_for_user(app: Application, user_id: int) -> str | None:
    pending = cast(dict[str, Any], app.bot_data.setdefault("sanchalak_pending", {}))
    timeout = _confirmation_timeout_seconds(app)
    now = time.time()
    active_action: str | None = None
    expired_tokens: list[str] = []
    for token, record in pending.items():
        created_at = float(record.get("created_at", 0.0))
        if now - created_at > timeout:
            expired_tokens.append(token)
            continue
        if int(record.get("user_id", -1)) == user_id:
            active_action = str(record.get("action", ""))
    for token in expired_tokens:
        pending.pop(token, None)
    return active_action


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    await message.reply_text(
        "SANCHALAK -- Global Control Bot\n\n"
        "I control run authorization, mode, and pause/resume actions across active scope.\n\n"
        + _HELP
    )


async def cmd_start_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    app = context.application
    state = app.bot_data.get("state")
    modules = cast(dict[str, Any], app.bot_data.get("modules", {}))

    _set_global_enabled(app, True)
    _state_set(state, "algo.paused", False)

    started: list[str] = []
    skipped: list[str] = []
    for name, module in modules.items():
        try:
            if getattr(module, "is_enabled", lambda: True)() and not getattr(
                module, "is_running", False
            ):
                module.start()
                started.append(name)
            else:
                skipped.append(name)
        except Exception as exc:
            logger.warning("SANCHALAK start_all failed for %s: %s", name, exc)
            skipped.append(name)

    paused_map = _paused_apps_map(state)
    for app_name in _app_names(app):
        paused_map[app_name] = False
    _save_paused_apps_map(state, paused_map)

    await message.reply_text(
        "SANCHALAK start_all completed\n\n"
        f"Global enabled: yes\n"
        f"Mode: {_mode_now(app)}\n"
        f"Modules started: {', '.join(started) if started else 'none'}\n"
        f"Modules unchanged: {', '.join(skipped) if skipped else 'none'}"
    )


def _new_pending_token(app: Application, action: str, user_id: int, payload: dict[str, Any]) -> str:
    token = f"{action}:{user_id}:{int(time.time() * 1000)}"
    pending = cast(dict[str, Any], app.bot_data.setdefault("sanchalak_pending", {}))
    pending[token] = {
        "action": action,
        "user_id": user_id,
        "created_at": time.time(),
        "payload": payload,
    }
    return token


def _pending_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirm", callback_data=f"{_CB}:ok:{token}"),
                InlineKeyboardButton("Cancel", callback_data=f"{_CB}:cancel:{token}"),
            ]
        ]
    )


async def cmd_stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    user_id = int(message.from_user.id) if message.from_user else 0
    active_action = _active_pending_action_for_user(context.application, user_id)
    if active_action:
        await message.reply_text(
            f"Finish or cancel the pending SANCHALAK action first: {active_action}."
        )
        return
    token = _new_pending_token(context.application, "stop_all", user_id, {})
    timeout = _confirmation_timeout_seconds(context.application)
    await message.reply_text(
        f"Confirm /stop_all?\nThis will set global authorization OFF and stop running modules.\nTimeout: {timeout}s",
        reply_markup=_pending_keyboard(token),
    )


async def cmd_set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    if not context.args:
        await message.reply_text("Usage: /set_mode <mock|live>")
        return
    mode = context.args[0].strip().lower()
    if mode not in {"mock", "live"}:
        await message.reply_text("Invalid mode. Use /set_mode mock or /set_mode live")
        return

    user_id = int(message.from_user.id) if message.from_user else 0
    active_action = _active_pending_action_for_user(context.application, user_id)
    if active_action:
        await message.reply_text(
            f"Finish or cancel the pending SANCHALAK action first: {active_action}."
        )
        return
    token = _new_pending_token(context.application, "set_mode", user_id, {"mode": mode})
    timeout = _confirmation_timeout_seconds(context.application)
    await message.reply_text(
        f"Confirm /set_mode {mode}?\nThis applies globally to all in-scope bots immediately.\nTimeout: {timeout}s",
        reply_markup=_pending_keyboard(token),
    )


async def _execute_stop_all(app: Application) -> str:
    state = app.bot_data.get("state")
    modules = cast(dict[str, Any], app.bot_data.get("modules", {}))
    _set_global_enabled(app, False)
    _state_set(state, "algo.paused", True)

    stopped: list[str] = []
    for name, module in modules.items():
        try:
            if getattr(module, "is_running", False):
                module.stop()
                stopped.append(name)
        except Exception as exc:
            logger.warning("SANCHALAK stop_all failed for %s: %s", name, exc)

    paused_map = _paused_apps_map(state)
    for app_name in _app_names(app):
        if app_name != "sanchalak":
            paused_map[app_name] = True
    _save_paused_apps_map(state, paused_map)
    return (
        "SANCHALAK stop_all confirmed\n\n"
        "Global enabled: no\n"
        f"Mode: {_mode_now(app)}\n"
        f"Modules stopped: {', '.join(stopped) if stopped else 'none'}"
    )


async def _execute_set_mode(app: Application, mode: str) -> str:
    state = app.bot_data.get("state")
    _state_set(state, "control.runtime_mode", mode)
    _set_mode_for_all_apps(app, mode)
    return f"SANCHALAK mode updated globally to: {mode}"


async def cb_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3:
        return

    decision = parts[1]
    token = parts[2]
    app = context.application
    pending = cast(dict[str, Any], app.bot_data.setdefault("sanchalak_pending", {}))
    record = pending.get(token)
    if not record:
        await query.edit_message_text("Action not found or already handled.")
        return

    timeout = _confirmation_timeout_seconds(app)
    if time.time() - float(record.get("created_at", 0.0)) > timeout:
        pending.pop(token, None)
        await query.edit_message_text(
            f"Confirmation timed out ({timeout}s). Action auto-cancelled."
        )
        return

    actor = int(query.from_user.id) if query.from_user else -1
    owner = int(record.get("user_id", -1))
    if actor != owner:
        await query.answer("Only the initiator can confirm this action.", show_alert=True)
        return

    if decision == "cancel":
        pending.pop(token, None)
        await query.edit_message_text("Action cancelled.")
        return

    action = str(record.get("action", ""))
    payload = cast(dict[str, Any], record.get("payload", {}))
    pending.pop(token, None)

    if action == "stop_all":
        text = await _execute_stop_all(app)
        await query.edit_message_text(text)
        return
    if action == "set_mode":
        mode = str(payload.get("mode", "mock"))
        text = await _execute_set_mode(app, mode)
        await query.edit_message_text(text)
        return

    await query.edit_message_text("Unknown pending action.")


async def cmd_pause_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    if not context.args:
        await message.reply_text("Usage: /pause_bot <target>")
        return

    target = context.args[0].strip().lower()
    app = context.application
    state = app.bot_data.get("state")
    modules = cast(dict[str, Any], app.bot_data.get("modules", {}))
    apps = cast(dict[str, Any], app.bot_data.get("apps", {}))

    if target in modules:
        module = modules[target]
        if getattr(module, "is_running", False):
            module.stop()
            await message.reply_text(f"Paused module: {target}")
        else:
            await message.reply_text(f"Module already paused/not running: {target}")
        return

    if target == "sanchalak":
        await message.reply_text(
            "SANCHALAK cannot be paused because it is the active control plane."
        )
        return

    if target in apps:
        paused_map = _paused_apps_map(state)
        paused_map[target] = True
        _save_paused_apps_map(state, paused_map)
        apps[target].bot_data["paused_by_sanchalak"] = True
        await message.reply_text(f"Paused bot: {target}. Read-only commands remain available.")
        return

    known = sorted(set(_module_names(app) + _app_names(app)))
    await message.reply_text(f"Unknown target: {target}\nKnown targets: {', '.join(known)}")


async def cmd_resume_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    if not context.args:
        await message.reply_text("Usage: /resume_bot <target>")
        return

    target = context.args[0].strip().lower()
    app = context.application
    state = app.bot_data.get("state")
    modules = cast(dict[str, Any], app.bot_data.get("modules", {}))
    apps = cast(dict[str, Any], app.bot_data.get("apps", {}))

    if target in modules:
        module = modules[target]
        if getattr(module, "is_enabled", lambda: True)() and not getattr(
            module, "is_running", False
        ):
            module.start()
            await message.reply_text(f"Resumed module: {target}")
        else:
            await message.reply_text(f"Module already running/not enabled: {target}")
        return

    if target in apps:
        paused_map = _paused_apps_map(state)
        paused_map[target] = False
        _save_paused_apps_map(state, paused_map)
        apps[target].bot_data["paused_by_sanchalak"] = False
        await message.reply_text(f"Resumed bot flag for: {target}")
        return

    known = sorted(set(_module_names(app) + _app_names(app)))
    await message.reply_text(f"Unknown target: {target}\nKnown targets: {', '.join(known)}")


async def cmd_status_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = _require_message(update)
    app = context.application
    state = app.bot_data.get("state")
    modules = cast(dict[str, Any], app.bot_data.get("modules", {}))
    apps = cast(dict[str, Any], app.bot_data.get("apps", {}))

    global_enabled = bool(_state_get(state, "control.global_enabled", False))
    mode = _mode_now(app)
    algo_paused = bool(_state_get(state, "algo.paused", False))
    paused_map = _paused_apps_map(state)

    bot_lines = []
    for name in sorted(apps):
        paused = paused_map.get(name, False)
        bot_lines.append(f"- {name}: {'paused' if paused else 'active'}")

    module_lines = []
    for name, module in sorted(modules.items()):
        running = bool(getattr(module, "is_running", False))
        module_lines.append(f"- {name}: {'running' if running else 'stopped'}")

    await message.reply_text(
        "SANCHALAK status_all\n\n"
        f"Global enabled: {'yes' if global_enabled else 'no'}\n"
        f"Mode: {mode}\n"
        f"Algo paused: {'yes' if algo_paused else 'no'}\n\n"
        "Bots:\n" + "\n".join(bot_lines) + "\n\nModules:\n" + "\n".join(module_lines)
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    message = _require_message(update)
    text = (message.text or "").strip().lower()
    if text in ("hello", "hi"):
        await message.reply_text("SANCHALAK online. Use /status_all for global state.")
        return
    await message.reply_text(_HELP)


def build_application(broker=None, state=None, event_bus=None, config=None) -> Application:
    del broker, event_bus, config
    cfg = load_bot_config("sanchalak")
    app = Application.builder().token(cfg.bot_token).build()
    app.bot_data["chat_id"] = cfg.chat_id
    app.bot_data["params"] = cfg.params
    app.bot_data["state"] = state

    # Initialize default state keys on startup.
    _state_set(
        state, "control.global_enabled", bool(_state_get(state, "control.global_enabled", False))
    )
    _state_set(
        state,
        "control.runtime_mode",
        str(
            _state_get(state, "control.runtime_mode", cfg.params.get("default_mode", "mock"))
        ).lower(),
    )

    try:

        from bat_telegram.update_audit import attach_update_audit

        attach_update_audit(app)

    except Exception as _audit_exc:

        logging.getLogger(__name__).warning("update audit attach failed: %s", _audit_exc)

    

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("start_all", cmd_start_all))
    app.add_handler(CommandHandler("stop_all", cmd_stop_all))
    app.add_handler(CommandHandler("pause_bot", cmd_pause_bot))
    app.add_handler(CommandHandler("resume_bot", cmd_resume_bot))
    app.add_handler(CommandHandler("set_mode", cmd_set_mode))
    app.add_handler(CommandHandler("status_all", cmd_status_all))
    app.add_handler(CallbackQueryHandler(cb_pending, pattern=rf"^{_CB}:(ok|cancel):"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("SANCHALAK bot application built")
    return app
