"""KAVACH Telegram handlers — MarkdownV2 safety and menu button dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from telegram.error import BadRequest

from bat_telegram.bots.kavach2 import bot as kavach_bot
from core.batman_cleanup import format_cleanup_verification_message
from telegram import Update


def test_md2_escapes_reserved_chars() -> None:
    raw = "NIFTY (rest) — avg 123.45"
    escaped = kavach_bot._md2(raw)
    assert "\\(" in escaped
    assert "\\)" in escaped
    assert "\\." in escaped


def test_md2_code_escapes_symbol_dots() -> None:
    sym = "NIFTY02JUN2623500CE"
    escaped = kavach_bot._md2_code(sym)
    assert "NIFTY02JUN2623500CE" in escaped.replace("\\", "")


def test_cleanup_message_escapes_check_labels() -> None:
    body = format_cleanup_verification_message(
        all_ok=True,
        checks=[("No active deployment file in data/deployments", True)],
        registered_at="2026-06-02T10:00:00",
        completed_at="Monday 02-Jun-2026 at 14:00",
        archived_file="archive/batman_2026-06-02.json",
    )
    assert "data/deployments" in body
    assert "\\." in body or "`" in body


def _message_mock() -> MagicMock:
    message = MagicMock()
    message.reply_text = AsyncMock(return_value=None)
    message.chat_id = 1
    message.message_id = 1
    message.chat = MagicMock()
    message.chat.id = 1
    message.from_user = MagicMock()
    message.from_user.id = 1
    return message


def _context_mock(*, broker: object | None = MagicMock(), state: object | None = None) -> MagicMock:
    state = state or MagicMock()
    state.get = MagicMock(
        side_effect=lambda key, default=None: {
            "ato.ce_triggered": False,
            "ato.pe_triggered": False,
            "algo.paused": False,
            "algo.pause_reason": None,
        }.get(key, default)
    )
    ctx = MagicMock()
    ctx.bot_data = {"broker": broker, "state": state, "event_bus": None}
    return ctx


@pytest.mark.asyncio
async def test_cmd_status_with_deployment_file() -> None:
    message = _message_mock()
    update = Update(update_id=1, message=message)
    dep = Path("batman_2026-06-02_14-00.json")
    reply = AsyncMock()

    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=dep),
        patch.object(kavach_bot, "_reply_md2", reply),
    ):
        await kavach_bot.cmd_status(update, _context_mock())

    reply.assert_awaited_once()
    text = reply.await_args.args[1]
    assert "KAVACH Status" in text
    assert kavach_bot._md2_code(dep.name) in text


@pytest.mark.asyncio
async def test_cmd_ato_status_shows_nifty_fire_levels() -> None:
    message = _message_mock()
    update = Update(update_id=1, message=message)
    dep = Path("batman_test.json")
    state = MagicMock()
    state.get.side_effect = lambda key, default=None: {
        "ato.ce_triggered": False,
        "ato.pe_triggered": False,
        "ato.ce_protect_symbol": None,
        "ato.pe_protect_symbol": "NIFTY-Jul2026-24000-PE",
        "ato.ce_entry_buffer_points": 10,
        "ato.pe_entry_buffer_points": 0,
        "ato.ce_retrace_points": 20,
        "ato.pe_retrace_points": 20,
        "ato.retrace_points": 5,
        "ato.poll_interval_seconds": 3,
        "ato.manage_sides": "pe",
    }.get(key, default)

    reply = AsyncMock()
    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=dep),
        patch.object(kavach_bot, "_reply_md2", reply),
        patch.object(kavach_bot, "_main_menu_keyboard", return_value=MagicMock()),
        patch(
            "builtins.open",
            mock_open(
                read_data=(
                    '{"positions":{"ce_sell":null,"pe_sell":{"strike":24050}},'
                    '"ato":{"ce_entry_buffer_points":10,"pe_entry_buffer_points":0,'
                    '"ce_retrace_points":20,"pe_retrace_points":20,'
                    '"poll_interval_seconds":3,"manage_sides":"pe",'
                    '"pe_protect_symbol":"NIFTY-Jul2026-24000-PE"}}'
                ),
            ),
        ),
    ):
        await kavach_bot.cmd_ato_status(update, _context_mock(state=state))

    text = reply.await_args.args[1]
    assert "ATO Status" in text
    assert "cache stale" not in text
    assert "NIFTY Spot" not in text
    assert "Schedule" in text
    assert "24,050" in text  # PE fires ≤ strike - entry
    assert "24,070" in text  # PE retrace exit ≥ strike + retrace
    assert "Fires ≤" in text
    assert "Retrace exit ≥" in text
    assert "NIFTY-Jul2026-24000-PE" in text


def test_find_kavach_logo_resolves_project_png() -> None:
    logo = kavach_bot._find_kavach_logo()
    assert logo is not None
    assert logo.is_file()
    assert logo.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


@pytest.mark.asyncio
async def test_cmd_positions_formats_rows() -> None:
    message = _message_mock()
    update = Update(update_id=1, message=message)
    broker = MagicMock()
    core_leg = {
        "symbol": "NIFTY02JUN2624000CE",
        "direction": "SELL",
        "qty": 130,
        "avg_price": 142.70,
        "display_symbol": "NIFTY 09 Jun 2026 24000 CE",
        "opt_type": "CE",
        "strike": 24000,
    }
    ato_leg = {
        "symbol": "NIFTY02JUN2623500CE",
        "direction": "LONG",
        "qty": 65,
        "avg_price": 123.45,
        "display_symbol": "NIFTY 09 Jun 2026 23500 CE",
        "opt_type": "CE",
        "strike": 23500,
    }
    protect = {
        "NIFTY02JUN2623500CE": {
            "side": "CE",
            "strike": 23500,
            "opt_type": "CE",
            "triggered": True,
        },
        "NIFTY02JUN2624000PE": {
            "side": "PE",
            "strike": 24000,
            "opt_type": "PE",
            "triggered": False,
        },
    }
    reply = AsyncMock()
    with (
        patch.object(
            kavach_bot, "_filter_nifty_positions", return_value=[core_leg, ato_leg]
        ),
        patch.object(
            kavach_bot, "_uat_enrich_positions_list", return_value=[core_leg, ato_leg]
        ),
        patch.object(kavach_bot, "_collect_ato_protect_symbols", return_value=protect),
        patch.object(kavach_bot, "_reply_md2", reply),
        patch.object(
            kavach_bot.asyncio,
            "to_thread",
            new=AsyncMock(return_value=MagicMock()),
        ),
    ):
        await kavach_bot.cmd_positions(update, _context_mock(broker=broker))

    text = reply.await_args.args[1]
    assert "ATO Positions" in text
    assert "23500" in text
    assert "LONG" in text
    assert "65" in text
    assert "24000 CE" not in text  # core Batman sell leg filtered out


def test_menu_handler_map_covers_buttons() -> None:
    assert set(kavach_bot._menu_action_handlers()) == {
        "positions",
        "ato_status",
        "corelegs",
        "status",
        "environment",
        "pause",
        "resume",
        "batman_complete",
        "recovery_operator",
        "recovery_auto",
        "recovery_auto_confirm",
        "resume_blocked",
    }


def test_main_menu_omits_funds_and_start_algo() -> None:
    import inspect

    src = inspect.getsource(kavach_bot._main_menu_keyboard)
    assert '"Funds"' not in src and "'Funds'" not in src
    assert "Start Algo Now" not in src
    assert "Kavach Status" in src
    assert "📊 ATO" in src
    assert "Positions" not in src
    assert 'InlineKeyboardButton("Status"' not in src
    assert "InlineKeyboardButton('Status'" not in src


def test_main_menu_layout_locked() -> None:
    """Operator-locked KAVACH 2.0 keyboard — no dynamic feed-recovery buttons."""
    import inspect
    import re

    src = inspect.getsource(kavach_bot._main_menu_keyboard)
    assert "show_recovery_control_buttons" not in src
    assert "kavach_resume_button_spec" not in src
    assert "recovery_operator" not in src
    assert "recovery_auto" not in src
    assert "resume_blocked" not in src
    assert 'callback_data=f"{_CB_MENU}:resume"' in src
    texts = re.findall(r'InlineKeyboardButton\(\s*"([^"]+)"', src, flags=re.DOTALL)
    assert texts == [
        "🛡️ Kavach Status",
        "🎯 ATO Status",
        "📊 ATO",
        "🎚️ Buffer Manager",
        "🧩 Core Legs",
        "🌐 Environment",
        "⏸️ Pause",
        "▶️ Resume",
        "🦇 Register Batman",
        "✅ Complete Batman",
    ]

def test_menu_handler_map_uses_live_callables() -> None:
    target = AsyncMock()
    with patch.object(kavach_bot, "cmd_status", target):
        handler = kavach_bot._menu_action_handlers()["status"]
    assert handler is target


def test_buffer_step_title_escapes_retrace_parens() -> None:
    from bat_telegram.bots.kavach2.register_wizard import _buffer_step_title

    ctx = MagicMock()
    ctx.user_data = {"wiz_plan": ["ce_exit"]}
    title = _buffer_step_title(ctx, "ce_exit")
    assert r"\(retrace\)" in title
    assert "exit (retrace)" not in title


@pytest.mark.asyncio
async def test_wizard_edit_step_plain_fallback_on_parse_error() -> None:
    query = MagicMock()
    message = MagicMock()
    message.chat_id = 1
    message.message_id = 10
    message.reply_text = AsyncMock(return_value=MagicMock(message_id=11))
    query.message = message
    query.edit_message_text = AsyncMock(
        side_effect=BadRequest("Can't parse entities: character '(' is reserved"),
    )
    context = MagicMock()
    context.user_data = {}
    context.bot.edit_message_text = AsyncMock()

    await kavach_bot._wizard_edit_step(
        context,
        query,
        "*CE exit \\(retrace\\) buffer — select mode:*",
    )

    plain_call = query.edit_message_text.await_args_list[-1]
    assert plain_call.kwargs.get("parse_mode") is None
    assert "(" in plain_call.args[0]


@pytest.mark.asyncio
async def test_reply_md2_falls_back_on_bad_request() -> None:
    message = _message_mock()
    message.reply_text = AsyncMock(
        side_effect=[BadRequest("Can't parse entities"), None],
    )

    await kavach_bot._reply_md2(message, r"Test \(parens\)", reply_markup=None)
    assert message.reply_text.await_count == 2
    second_kwargs = message.reply_text.await_args_list[1].kwargs
    assert second_kwargs.get("parse_mode") is None


@pytest.mark.asyncio
async def test_send_alive_menu_sends_clear_logo_then_caption() -> None:
    message = _message_mock()
    message.reply_photo = AsyncMock()
    logo = Path("kavach_logo.png")
    with (
        patch.object(kavach_bot, "_find_kavach_logo", return_value=logo),
        patch.object(kavach_bot, "_logo_photo_input", return_value=MagicMock()),
        patch.object(kavach_bot, "_main_menu_keyboard", return_value=MagicMock()),
        patch.object(kavach_bot, "_find_active_deployment", return_value=None),
    ):
        await kavach_bot._send_alive_menu(message)
    message.reply_photo.assert_awaited_once()
    kwargs = message.reply_photo.await_args.kwargs
    assert "KAVACH 2.0 alive" in kwargs["caption"]
    assert kwargs.get("parse_mode") is not None
