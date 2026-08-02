from __future__ import annotations

from telegram.ext import ContextTypes

from telegram import Update


def current_command_name(update: Update) -> str:
    message = update.message
    text = (message.text or "").strip() if message else ""
    if not text.startswith("/"):
        return ""
    return text.split()[0][1:].split("@", 1)[0].lower()


def is_bot_paused(application, bot_name: str) -> bool:
    state = application.bot_data.get("state")
    if state is None:
        return False
    try:
        paused = state.get("control.paused_apps", {})
    except Exception:
        return False
    if not isinstance(paused, dict):
        return False
    return bool(paused.get(bot_name, False))


async def guard_paused_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    bot_name: str,
    read_only_commands: set[str],
) -> bool:
    command_name = current_command_name(update)
    if not is_bot_paused(context.application, bot_name):
        return True
    if command_name in read_only_commands:
        return True

    message = update.message
    if message is not None:
        shown_command = f"/{command_name}" if command_name else "this command"
        await message.reply_text(
            f"{bot_name.upper()} is paused by SANCHALAK. "
            f"Read-only commands are still allowed, but {shown_command} is blocked until SANCHALAK resumes {bot_name}."
        )
    return False
