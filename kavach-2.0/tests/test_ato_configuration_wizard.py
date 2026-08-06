"""Tests for KAVACH ATO Configuration (Quick Tune) — buffers-only."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bat_telegram.bots.kavach2.ato_configuration_wizard as tune
import bat_telegram.bots.kavach2.bot as kavach_bot
from core.buffer_config.schema import BufferKind, normalize_buffer_field, serialize_buffer_field
from telegram.ext import ConversationHandler


class _FakeUpdate:
    def __init__(self, update_id: int, message=None, callback_query=None):
        self.update_id = update_id
        self.message = message
        self.callback_query = callback_query
        self.effective_message = message or (
            getattr(callback_query, "message", None) if callback_query else None
        )


def _message_mock() -> MagicMock:
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    return msg


def _query_mock(data: str, message: MagicMock | None = None) -> MagicMock:
    q = MagicMock()
    q.data = data
    q.message = message or _message_mock()
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    return q


def _context_mock(*, state=None, user_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {"state": state, "params": {"ato": {}}}
    ctx.user_data = user_data if user_data is not None else {}
    return ctx


def test_queue_for_sides_order() -> None:
    assert tune._queue_for_sides("ce") == ["ce_entry", "ce_exit"]
    assert tune._queue_for_sides("pe") == ["pe_entry", "pe_exit"]
    assert tune._queue_for_sides("both") == [
        "ce_entry",
        "ce_exit",
        "pe_entry",
        "pe_exit",
    ]


def test_apply_patches_dict_writes_typed_and_legacy() -> None:
    ato: dict = {}
    dep: dict = {}
    patches = {
        "ce_entry": serialize_buffer_field(
            normalize_buffer_field(7), BufferKind.PREDEFINED
        ),
        "ce_exit": serialize_buffer_field(
            normalize_buffer_field(12), BufferKind.PREDEFINED
        ),
    }
    tune.apply_patches_dict(ato, dep, patches)
    assert ato["ce_entry_buffer"]["value"] == "7"
    assert ato["ce_entry_buffer_points"] == 7
    assert ato["ce_retrace_points"] == 12
    assert dep["retrace_points"] == 12


def test_apply_ato_buffer_patch_updates_file_and_state(tmp_path: Path) -> None:
    deploy_dir = tmp_path / "deployments"
    deploy_dir.mkdir()
    path = deploy_dir / "batman_2026-07-15_21-00.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1.1,
                "retrace_points": 5,
                "ato": {
                    "ce_entry_buffer_points": 0,
                    "pe_entry_buffer_points": 0,
                    "ce_retrace_points": 5,
                    "pe_retrace_points": 5,
                },
            }
        ),
        encoding="utf-8",
    )
    state = MagicMock()
    state.set = MagicMock()
    state.save = MagicMock()
    patches = {
        "ce_exit": serialize_buffer_field(
            normalize_buffer_field(10), BufferKind.PREDEFINED
        )
    }

    with (
        patch.object(kavach_bot, "_DEPLOY_DIR", deploy_dir),
        patch.object(kavach_bot, "_mirror_deployment_to_daily_audit"),
        patch.object(kavach_bot, "_append_log"),
        patch("bat_telegram.bots.kavach2.bot.deployment_session") as sess,
    ):
        sess.return_value.__enter__ = MagicMock(return_value=None)
        sess.return_value.__exit__ = MagicMock(return_value=False)
        out = kavach_bot.apply_ato_buffer_patch(patches, state=state)

    assert out == path
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ato"]["ce_retrace_points"] == 10
    assert data["retrace_points"] == 10
    state.set.assert_any_call(
        "ato.ce_retrace_points", normalize_buffer_field(10), save=False
    )
    # Must not touch triggered flags
    called_keys = [c.args[0] for c in state.set.call_args_list]
    assert "ato.ce_triggered" not in called_keys


@pytest.mark.asyncio
async def test_tune_entry_not_armed() -> None:
    message = _message_mock()
    update = _FakeUpdate(1, message=message)
    ctx = _context_mock()
    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=None),
        patch.object(kavach_bot, "_reply_md2", new=AsyncMock()) as reply,
        patch.object(kavach_bot, "_main_menu_keyboard", return_value=MagicMock()),
    ):
        result = await tune.tune_entry(update, ctx)
    assert result == ConversationHandler.END
    text = reply.await_args.args[1]
    assert "Register first" in text.replace("\\", "")


@pytest.mark.asyncio
async def test_tune_side_pick_opens_first_buffer(tmp_path: Path) -> None:
    path = tmp_path / "batman_x.json"
    path.write_text(
        json.dumps(
            {
                "retrace_points": 5,
                "ato": {
                    "ce_entry_buffer_points": 2,
                    "ce_retrace_points": 8,
                    "pe_entry_buffer_points": 1,
                    "pe_retrace_points": 6,
                },
            }
        ),
        encoding="utf-8",
    )
    query = _query_mock(f"{tune._CB_SIDE}:ce")
    update = _FakeUpdate(2, callback_query=query)
    ctx = _context_mock()
    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=path),
        patch.object(kavach_bot, "_safe_answer_callback", new=AsyncMock()),
        patch.object(kavach_bot, "_wizard_edit_step", new=AsyncMock()) as edit,
    ):
        result = await tune.tune_side_pick(update, ctx)
    assert result == tune.TUNE_BUF_MODE
    assert ctx.user_data["atc_queue"] == ["ce_entry", "ce_exit"]
    assert ctx.user_data["atc_idx"] == 0
    edit.assert_awaited()
    body = edit.await_args.args[2]
    assert "CE entry" in body.replace("\\", "")


@pytest.mark.asyncio
async def test_keep_current_advances_to_confirm() -> None:
    query = _query_mock(f"{tune._CB_BUF}:ce_entry:keep")
    update = _FakeUpdate(3, callback_query=query)
    ctx = _context_mock(
        user_data={
            "atc_queue": ["ce_entry", "ce_exit"],
            "atc_idx": 0,
            "atc_baseline": {"ce_entry": 2, "ce_exit": 5},
            "atc_pending": {"ce_entry": 2, "ce_exit": 5},
            "atc_holding": {"ce": False, "pe": False},
        }
    )
    with (
        patch.object(kavach_bot, "_safe_answer_callback", new=AsyncMock()),
        patch.object(kavach_bot, "_wizard_edit_step", new=AsyncMock()) as edit,
    ):
        result = await tune.tune_buffer_action(update, ctx)
        # second keep
        query2 = _query_mock(f"{tune._CB_BUF}:ce_exit:keep")
        update2 = _FakeUpdate(4, callback_query=query2)
        result2 = await tune.tune_buffer_action(update2, ctx)
    assert result == tune.TUNE_BUF_MODE
    assert result2 == tune.TUNE_CONFIRM
    assert "confirm" in edit.await_args.args[2].lower()


def test_menu_keyboard_includes_ato_configuration() -> None:
    """Under telegram stub (MagicMock), assert button construction args."""
    kavach_bot.InlineKeyboardButton.reset_mock()
    with (
        patch.object(kavach_bot, "_read_algo_pause_reason", return_value=None),
        patch(
            "core.feed_recovery.show_recovery_control_buttons",
            return_value=False,
        ),
        patch(
            "core.feed_recovery.kavach_resume_button_spec",
            return_value=("Resume", "resume"),
        ),
    ):
        kavach_bot._main_menu_keyboard()
    texts: list[str] = []
    callbacks: list[str] = []
    for call in kavach_bot.InlineKeyboardButton.call_args_list:
        if call.args:
            texts.append(str(call.args[0]))
        if "text" in call.kwargs:
            texts.append(str(call.kwargs["text"]))
        if len(call.args) > 1:
            pass
        cb = call.kwargs.get("callback_data")
        if cb:
            callbacks.append(str(cb))
    assert "ATO Configuration" in texts
    assert f"{kavach_bot._CB_MENU}:ato_tune" in callbacks


@pytest.mark.asyncio
async def test_on_menu_callback_skips_ato_tune() -> None:
    query = _query_mock(f"{kavach_bot._CB_MENU}:ato_tune")
    update = _FakeUpdate(5, callback_query=query)
    with (
        patch.object(kavach_bot, "_safe_answer_callback", new=AsyncMock()),
        patch.object(kavach_bot, "_send_alive_menu", new=AsyncMock()) as alive,
    ):
        await kavach_bot.on_menu_callback(update, _context_mock())
    alive.assert_not_awaited()
