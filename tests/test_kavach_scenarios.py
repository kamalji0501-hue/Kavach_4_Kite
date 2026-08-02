"""KAVACH end-to-end handler scenarios (unit level, mocked Telegram/Dhan)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from telegram.error import BadRequest

from bat_telegram.bots.kavach import bot as kavach_bot
from bat_telegram.bots.kavach.register_wizard import (
    WIZARD_CE_INTENT,
    WIZARD_PE_BUY,
    _buffer_kind_label,
    _buffer_step_title,
    _lots_prompt_md,
    wizard_buffer_mode,
    wizard_pe_intent,
)
from core.buffer_config.schema import BufferKind, serialize_buffer_field


class _FakeUpdate:
    """Minimal update object (telegram.Update is mocked in conftest)."""

    def __init__(
        self,
        update_id: int = 1,
        *,
        message: MagicMock | None = None,
        callback_query: MagicMock | None = None,
    ) -> None:
        self.update_id = update_id
        self.message = message
        self.callback_query = callback_query
        self.effective_message = message or (
            callback_query.message if callback_query is not None else None
        )


def _message_mock() -> MagicMock:
    message = MagicMock()
    message.reply_text = AsyncMock(return_value=MagicMock(message_id=99))
    message.chat_id = 1
    message.message_id = 1
    message.chat = MagicMock()
    message.chat.id = 1
    message.from_user = MagicMock()
    message.from_user.id = 1
    message.text = "/status"
    return message


def _query_mock(data: str) -> MagicMock:
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.message = _message_mock()
    query.edit_message_text = AsyncMock()
    return query


def _context_mock(
    *,
    broker: object | None = MagicMock(),
    state: object | None = None,
    user_data: dict | None = None,
    params: dict | None = None,
) -> MagicMock:
    if state is None:
        state = MagicMock()
        state.get = MagicMock(
            side_effect=lambda key, default=None: {
                "ato.ce_triggered": False,
                "ato.pe_triggered": False,
                "algo.paused": False,
                "algo.pause_reason": None,
                "ratripal.pending.request_id": "req-1",
            }.get(key, default)
        )
        state.set = MagicMock()
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot_data = {
        "broker": broker,
        "state": state,
        "event_bus": None,
        "params": params
        or {
            "strategy": {"lot_size": 65},
            "ato": {
                "predefined_entry_buffers": [0, 5, 10],
                "predefined_exit_buffers": [5, 10, 20],
            },
            "deploy_wizard": {"ato_step": 50},
        },
    }
    ctx.application = MagicMock()
    ctx.application.bot_data = ctx.bot_data
    ctx.bot = MagicMock()
    ctx.bot.edit_message_text = AsyncMock()
    return ctx


def _sample_positions() -> list[dict]:
    return [
        {
            "symbol": "NIFTY02JUN2624000PE",
            "direction": "LONG",
            "qty": 65,
            "avg_price": 120.5,
            "strike": 24000,
        },
        {
            "symbol": "NIFTY02JUN2623500PE",
            "direction": "SHORT",
            "qty": 65,
            "avg_price": 98.25,
            "strike": 23500,
        },
        {
            "symbol": "NIFTY02JUN2624000CE",
            "direction": "LONG",
            "qty": 65,
            "avg_price": 110.0,
            "strike": 24000,
        },
        {
            "symbol": "NIFTY02JUN2624500CE",
            "direction": "SHORT",
            "qty": 65,
            "avg_price": 85.5,
            "strike": 24500,
        },
    ]


@pytest.fixture(autouse=True)
def _allow_commands():
    kavach_bot.ConversationHandler.END = -1
    with patch(
        "bat_telegram.bots.kavach.bot.guard_paused_command",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.mark.parametrize(
    "cmd_name,handler_attr,no_dep_phrase",
    [
        ("pause", "cmd_pause", "No deployment registered"),
        ("resume", "cmd_resume", "No deployment"),
        ("start_algo", "cmd_start_now", "No deployment"),
        ("corelegs", "cmd_legs", "No active deployment"),
        ("ato_status", "cmd_ato_status", "No active deployment"),
    ],
)
@pytest.mark.asyncio
async def test_commands_without_deployment(cmd_name, handler_attr, no_dep_phrase) -> None:
    message = _message_mock()
    update = _FakeUpdate(1, message=message)
    handler = getattr(kavach_bot, handler_attr)
    reply = AsyncMock()

    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=None),
        patch.object(kavach_bot, "_reply_md2", reply),
    ):
        await handler(update, _context_mock())

    text = reply.await_args.args[1]
    assert no_dep_phrase.split()[0] in text or "deployment" in text.lower()


@pytest.mark.asyncio
async def test_cmd_funds_with_broker() -> None:
    message = _message_mock()
    update = _FakeUpdate(1, message=message)
    broker = MagicMock()
    broker.get_balance = MagicMock(return_value=250_000.5)
    reply = AsyncMock()

    with (
        patch.object(kavach_bot, "_reply_md2", reply),
        patch.object(kavach_bot.asyncio, "to_thread", new=AsyncMock(return_value=250_000.5)),
    ):
        await kavach_bot.cmd_funds(update, _context_mock(broker=broker))

    assert "Margin" in reply.await_args.args[1]


@pytest.mark.asyncio
async def test_cmd_legs_with_deployment_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BATMAN_MODE", "uat")
    message = _message_mock()
    update = _FakeUpdate(1, message=message)
    dep = Path("batman_test.json")
    payload = (
        '{"positions":{"pe_buy":{"symbol":"NIFTY02JUN2624000PE","qty":65,"avg_price":120.5},'
        '"pe_sell":{"symbol":"NIFTY02JUN2623500PE","qty":65,"avg_price":98.25}}}'
    )
    reply = AsyncMock()

    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=dep),
        patch.object(kavach_bot, "_reply_md2", reply),
        patch.object(kavach_bot, "_read_algo_pause_reason", return_value=None),
        patch("builtins.open", mock_open(read_data=payload)),
    ):
        await kavach_bot.cmd_legs(update, _context_mock())

    text = reply.await_args.args[1]
    assert "Batman Legs" in text
    assert kavach_bot._md2_code("NIFTY02JUN2624000PE") in text


class _FakeState:
    def __init__(self, values: dict) -> None:
        self._values = values

    def get(self, key: str, default=None):
        return self._values.get(key, default)


@pytest.mark.asyncio
async def test_cmd_status_paused_reason_escaped() -> None:
    message = _message_mock()
    update = _FakeUpdate(1, message=message)
    state = _FakeState(
        {
            "ato.ce_triggered": False,
            "ato.pe_triggered": False,
            "algo.paused": True,
            "algo.pause_reason": "manual (operator)",
        }
    )
    reply = AsyncMock()

    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=None),
        patch.object(kavach_bot, "_reply_md2", reply),
    ):
        await kavach_bot.cmd_status(update, _context_mock(state=state))

    text = reply.await_args.args[1]
    assert "Paused" in text
    assert "operator" in text.replace("\\", "")


@pytest.mark.parametrize("action", list(kavach_bot._menu_action_handlers().keys()))
@pytest.mark.asyncio
async def test_menu_callback_dispatches(action: str) -> None:
    query = _query_mock(f"{kavach_bot._CB_MENU}:{action}")
    update = _FakeUpdate(3, callback_query=query)
    target = AsyncMock()
    handlers = {**kavach_bot._menu_action_handlers(), action: target}

    with (
        patch.object(kavach_bot, "_safe_answer_callback", new=AsyncMock(return_value=True)),
        patch.object(kavach_bot, "_menu_action_handlers", return_value=handlers),
    ):
        await kavach_bot.on_menu_callback(update, _context_mock())

    target.assert_awaited_once()


@pytest.mark.asyncio
async def test_menu_callback_main_shows_alive_menu() -> None:
    query = _query_mock(f"{kavach_bot._CB_MENU}:main")
    update = _FakeUpdate(4, callback_query=query)

    with (
        patch.object(kavach_bot, "_safe_answer_callback", new=AsyncMock(return_value=True)),
        patch.object(kavach_bot, "_send_alive_menu", new=AsyncMock()) as alive,
    ):
        await kavach_bot.on_menu_callback(update, _context_mock())

    alive.assert_awaited_once()


@pytest.mark.asyncio
async def test_wizard_pe_intent_skip_goes_to_ce() -> None:
    query = _query_mock("wiz_side:pe:skip")
    update = _FakeUpdate(5, callback_query=query)
    ctx = _context_mock(user_data={"wiz_positions": _sample_positions()})
    edit = AsyncMock()

    with (
        patch.object(kavach_bot, "_safe_answer_callback", new=AsyncMock(return_value=True)),
        patch.object(kavach_bot, "_wizard_edit_step", edit),
    ):
        state = await wizard_pe_intent(update, ctx)

    assert state == WIZARD_CE_INTENT
    assert ctx.user_data["pe_enabled"] is False
    assert "CE side" in edit.await_args.args[2]


@pytest.mark.asyncio
async def test_wizard_pe_intent_enable_shows_long_pe() -> None:
    query = _query_mock("wiz_side:pe:enable")
    update = _FakeUpdate(6, callback_query=query)
    ctx = _context_mock(user_data={"wiz_positions": _sample_positions()})
    edit = AsyncMock()

    with (
        patch.object(kavach_bot, "_safe_answer_callback", new=AsyncMock(return_value=True)),
        patch.object(kavach_bot, "_wizard_edit_step", edit),
    ):
        state = await wizard_pe_intent(update, ctx)

    assert state == WIZARD_PE_BUY
    text = edit.await_args.args[2]
    assert r"\(LONG PE\)" in text


@pytest.mark.asyncio
async def test_wizard_buffer_mode_asks_predefined_for_ce_exit() -> None:
    query = _query_mock("wiz_bmode:ce_exit:pred")
    update = _FakeUpdate(7, callback_query=query)
    ctx = _context_mock(
        user_data={
            "wiz_positions": _sample_positions(),
            "ce_enabled": True,
            "pe_enabled": False,
        }
    )
    edit = AsyncMock()

    with (
        patch.object(kavach_bot, "_safe_answer_callback", new=AsyncMock(return_value=True)),
        patch.object(kavach_bot, "_wizard_edit_step", edit),
    ):
        await wizard_buffer_mode(update, ctx)

    assert "predefined" in edit.await_args.args[2].lower()


def test_buffer_labels_all_targets_md2_safe() -> None:
    ctx = MagicMock()
    ctx.user_data = {"wiz_plan": list(("ce_entry", "pe_entry", "ce_exit", "pe_exit"))}
    for target in ("ce_entry", "pe_entry", "ce_exit", "pe_exit"):
        label = _buffer_kind_label(target)
        if "entry" not in target:
            assert r"\(retrace\)" in label
        title = _buffer_step_title(ctx, target)
        assert "exit (retrace)" not in title


def test_lots_prompt_md_escapes_parens() -> None:
    ctx = MagicMock()
    ctx.user_data = {"wiz_plan": ["pe_lots"]}
    text = _lots_prompt_md(ctx, "PE", 65, 65, 65)
    assert r"\(" in text
    assert "qty (6" not in text.replace("\\(", "")


@pytest.mark.asyncio
async def test_wizard_show_summary_ce_exit_buffers() -> None:
    query = _query_mock("wiz_ato_mon:both")
    ctx = _context_mock(
        user_data={
            "pe_enabled": True,
            "ce_enabled": True,
            "pe_buy": _sample_positions()[0],
            "pe_sell": _sample_positions()[1],
            "ce_buy": _sample_positions()[2],
            "ce_sell": _sample_positions()[3],
            "pe_managed_lots": 1,
            "ce_managed_lots": 1,
            "wiz_ce_entry_buffer": serialize_buffer_field(Decimal("5"), BufferKind.PREDEFINED),
            "wiz_pe_entry_buffer": serialize_buffer_field(Decimal("3"), BufferKind.PREDEFINED),
            "wiz_ce_exit_buffer": serialize_buffer_field(Decimal("10"), BufferKind.PREDEFINED),
            "wiz_pe_exit_buffer": serialize_buffer_field(Decimal("15"), BufferKind.PREDEFINED),
            "wiz_poll_interval_seconds": 2,
            "wiz_ato_manage_sides": "both",
        }
    )
    edit = AsyncMock()

    with patch.object(kavach_bot, "_edit_md2", edit):
        state = await kavach_bot._wizard_show_summary(query, ctx)

    from bat_telegram.bots.kavach.register_wizard import WIZARD_CONFIRM

    assert state == WIZARD_CONFIRM
    text = edit.await_args.args[1]
    assert "Batman Position Summary" in text
    assert "CE trigger" in text
    assert "exit (retrace)" not in text


@pytest.mark.asyncio
async def test_batman_complete_cancel() -> None:
    query = _query_mock(f"{kavach_bot._CB_DONE}:cancel")
    update = _FakeUpdate(8, callback_query=query)

    await kavach_bot.on_batman_complete_callback(update, _context_mock())

    text = query.edit_message_text.await_args.args[0]
    assert "Cancelled" in text


@pytest.mark.asyncio
async def test_hedge_box_deny() -> None:
    query = _query_mock(f"{kavach_bot._CB_HB}:deny:req-1")
    update = _FakeUpdate(10, callback_query=query)
    ctx = _context_mock()

    await kavach_bot.on_hedge_box_callback(update, ctx)
    query.edit_message_text.assert_awaited()
    assert "denied" in query.edit_message_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_hedge_box_invalid_payload() -> None:
    query = _query_mock("hb:bad")
    update = _FakeUpdate(11, callback_query=query)

    await kavach_bot.on_hedge_box_callback(update, _context_mock())
    assert "Invalid" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_wizard_entry_uat_bootstraps_shadow_broker_without_startup_broker() -> None:
    """UAT register must not block on no_valid_token when fixture book exists."""
    from bat_telegram.bots.kavach.register_wizard import WIZARD_PE_INTENT

    message = _message_mock()
    update = _FakeUpdate(13, message=message)
    ctx = _context_mock(broker=None)
    shadow = MagicMock()
    shadow.token_age_hours = 1.0
    shadow.get_positions = MagicMock(return_value=MagicMock())
    shadow.refresh_fixture_positions = MagicMock()

    def _bootstrap(ctx):
        ctx.bot_data["broker"] = shadow
        return shadow

    with (
        patch.object(kavach_bot, "_append_log"),
        patch.object(kavach_bot, "_try_bootstrap_uat_broker", side_effect=_bootstrap),
        patch.object(kavach_bot, "_find_active_deployment", return_value=None),
        patch("core.batman_mode.is_uat", return_value=True),
        patch(
            "core.uat_register_cleanup.prepare_uat_register_fresh",
            return_value={"ok": True},
        ),
        patch(
            "core.uat_ingest.ingest_uat_for_register",
            return_value={"ok": True, "method": "cursor_chat"},
        ),
        patch.object(kavach_bot, "_filter_nifty_positions", return_value=[{"symbol": "NIFTY-TEST"}]),
        patch.object(
            kavach_bot,
            "_enrich_positions_list",
            return_value=[{"symbol": "NIFTY-TEST"}],
        ),
        patch.object(kavach_bot, "_wizard_show", new_callable=AsyncMock),
        patch(
            "bat_telegram.bots.kavach.bot.guard_paused_command",
            new=AsyncMock(return_value=True),
        ),
    ):
        state = await kavach_bot.wizard_entry(update, ctx)

    assert state == WIZARD_PE_INTENT
    assert ctx.bot_data["broker"] is shadow
    message.reply_text.assert_awaited()


@pytest.mark.asyncio
async def test_wizard_entry_no_broker_token_gate() -> None:
    message = _message_mock()
    update = _FakeUpdate(12, message=message)
    ctx = _context_mock(broker=None)

    with patch.object(kavach_bot, "_append_log"), patch("core.batman_mode.is_uat", return_value=False):
        state = await kavach_bot.wizard_entry(update, ctx)

    assert state == -1
    message.reply_text.assert_awaited()
    assert "Token" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_edit_md2_falls_back_on_bad_request() -> None:
    query = _query_mock("x")
    query.edit_message_text = AsyncMock(
        side_effect=[BadRequest("Can't parse entities"), None],
    )

    await kavach_bot._edit_md2(query, r"Bad \(md\)", reply_markup=None)
    assert query.edit_message_text.await_count == 2
    assert query.edit_message_text.await_args_list[1].kwargs.get("parse_mode") is None


@pytest.mark.asyncio
async def test_selected_header_escapes_symbol_parens() -> None:
    selected = {
        "pe_buy": {"symbol": "NIFTY(测试)PE", "qty": 1, "avg_price": 1.0},
    }
    header = kavach_bot._selected_header(selected)
    assert "\\(" in header or "测试" in header.replace("\\", "")
