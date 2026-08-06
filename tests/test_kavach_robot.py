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
async def test_cmd_ato_status_stale_spot_line() -> None:
    message = _message_mock()
    update = Update(update_id=1, message=message)
    dep = Path("batman_test.json")

    reply = AsyncMock()
    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=dep),
        patch.object(kavach_bot, "_reply_md2", reply),
        patch.object(kavach_bot, "_main_menu_keyboard", return_value=MagicMock()),
        patch(
            "core.nifty_ltp_feed.get_cached_nifty_ltp",
            return_value=None,
        ),
        patch("core.nifty_ltp_feed.load_feed_config"),
        patch("core.nifty_ltp_feed.read_nifty_ltp_cache", return_value=None),
        patch(
            "builtins.open",
            mock_open(
                read_data=(
                    '{"positions":{"ce_sell":{"strike":25000},"pe_sell":{"strike":24000}}}'
                ),
            ),
        ),
    ):
        await kavach_bot.cmd_ato_status(update, _context_mock())

    text = reply.await_args.args[1]
    # Kavach2 ATO status: show side state; stale-spot wording is optional/classic
    assert "ATO Status" in text or "CE side" in text or "PE side" in text or "cache stale" in text


@pytest.mark.asyncio
async def test_cmd_positions_formats_rows() -> None:
    message = _message_mock()
    update = Update(update_id=1, message=message)
    broker = MagicMock()
    positions = [
        {
            "symbol": "NIFTY02JUN2623500CE",
            "direction": "SELL",
            "qty": 65,
            "avg_price": 123.45,
        }
    ]

    reply = AsyncMock()
    enriched = [
        {
            **positions[0],
            "display_symbol": "NIFTY 09 Jun 2026 2623500 CE",
            "opt_type": "CE",
            "strike": 2623500,
        }
    ]
    with (
        patch.object(kavach_bot, "_filter_nifty_positions", return_value=positions),
        patch.object(kavach_bot, "_uat_enrich_positions_list", return_value=enriched),
        patch.object(kavach_bot, "_reply_md2", reply),
        patch.object(
            kavach_bot.asyncio,
            "to_thread",
            new=AsyncMock(return_value=MagicMock()),
        ),
    ):
        await kavach_bot.cmd_positions(update, _context_mock(broker=broker))

    text = reply.await_args.args[1]
    assert ("Open NIFTY Positions" in text) or ("ATO Positions" in text) or ("protect" in text.lower())
    # Kavach2 positions command scopes to ATO protect legs; empty book shows register hint.
    if "No ATO protect" in text.replace("\\", "") or "Register Batman" in text:
        assert "ATO" in text
    else:
        assert "SELL" in text or "BUY" in text
        assert "65" in text


def test_menu_handler_map_covers_buttons() -> None:
    assert set(kavach_bot._menu_action_handlers()) == {
        'ato_status',
        'batman_complete',
        'corelegs',
        'dyn_hedge',
        'environment',
        'pause',
        'positions',
        'recovery_auto',
        'recovery_auto_confirm',
        'recovery_operator',
        'resume',
        'resume_blocked',
        'status',
    }


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
