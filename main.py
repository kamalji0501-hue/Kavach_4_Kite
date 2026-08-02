#!/usr/bin/env python3
"""
Batman v3 -- Main Orchestrator.

Run with:
    python main.py

Starts a single asyncio process containing the always-on bots plus any
optionally configured reporting bots.

Default runtime:
    * DRISHTI bot   -- token delivery, broker health, scheduled algo prompts
    * KAVACH bot    -- trading commands, ATO control, deployment wizard
    * LAKSHMI bot   -- MTM alerts, /pnl, EOD P&L summary

Optional runtime:
    * SARANSH bot   -- compact EOD/manual execution summary

Currently running 3 bots by default (DRISHTI + KAVACH + LAKSHMI).
All bots run as asyncio tasks (PTB v20+ Application.updater).
Trading modules (ATO, trailing, monitor, hedge, exit) run as daemon
threads managed by ModuleBase -- they are pre-tested at 129/129 and
unchanged by this rewrite.

Stop with Ctrl+C or SIGTERM.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

# -- Logging ------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("batman.main")

_BOT_CONFIG_DIR = Path(__file__).parent / "telegram" / "bots"


def _has_bot_secrets(bot_name: str) -> bool:
    return (_BOT_CONFIG_DIR / bot_name / "token.env").exists()


def _require_bot_config(bot_name: str) -> None:
    from bat_telegram.loader import load_bot_config

    load_bot_config(bot_name, reload_token=True, reload_params=True)


# -- Main coroutine -----------------------------------------------------------


async def batman_main() -> None:
    """Single asyncio coroutine -- wires every component and runs until stopped."""

    # 1. Configuration
    from core.config import Config

    config = Config.load(
        settings_path=Path(__file__).parent / "config" / "settings.json",
        env_path=Path(__file__).parent / "config" / ".env",
    )

    from core.runtime_logging import configure_runtime_logging

    workspace = Path(__file__).parent
    configure_runtime_logging(config.raw, workspace)
    from core.bot_logging import attach_main_incident_handler

    attach_main_incident_handler(workspace)
    logger.info("Config loaded")

    # 2. Broker  (token priority: persisted disk -> env var -> stub)
    #
    # DRISHTI bot calls broker.hot_reload_token() whenever the user sends a
    # fresh Dhan JWT -- no process restart needed.
    from core.broker import BatmanBroker
    from core.token_store import TokenStore

    token_store = TokenStore(path=Path(__file__).parent / "data" / "access_token.json")
    client_code = config.get("broker.client_code", "")

    stored_token, saved_at = token_store.load()
    if stored_token and not token_store.is_expired():
        logger.info("Broker: using persisted token (age=%.1fh)", token_store.token_age_hours())
        broker = BatmanBroker.connect_with_token(client_code, stored_token)
    elif config.get("broker.access_token"):
        logger.info("Broker: using access_token from config/env")
        broker = BatmanBroker.connect_with_token(client_code, config.get("broker.access_token"))
    else:
        logger.warning(
            "No Dhan access token found. "
            "Send a fresh token to DRISHTI bot before market opens. "
            "Batman will arm as soon as the token is hot-loaded."
        )
        from unittest.mock import MagicMock

        broker = BatmanBroker(MagicMock(), auth_time=None)

    logger.info("Broker ready")

    # 3. State + EventBus
    from core.event_bus import EventBus
    from core.state import StateManager

    state = StateManager(path=Path(__file__).parent / "data" / "batman_state.json")
    events = EventBus()
    state.set("control.global_enabled", False)
    state.set("control.paused_apps", {})
    broker.set_runtime_mode_provider(
        lambda: str(state.get("control.runtime_mode", "live") or "live")
    )
    _require_bot_config("jagran")
    logger.info("State and EventBus initialized")
    logger.info("JAGRAN config validated")

    # 4. Algo modules (daemon threads -- ModuleBase, tested 129/129, do not convert)
    #
    # These use threading.Thread internally. They are thread-safe and communicate
    # via the shared EventBus. Not converted to asyncio to preserve test coverage.
    from modules.ato_protection import ATOProtection
    from modules.emergency_exit import EmergencyExit
    from modules.overnight_hedge import OvernightHedge
    from modules.position_monitor import PositionMonitor
    from modules.profit_trailing import ProfitTrailing
    from modules.ratripal import Ratripal

    modules = {
        "ato_protection": ATOProtection(broker, config, state, events),
        "profit_trailing": ProfitTrailing(broker, config, state, events),
        "overnight_hedge": OvernightHedge(broker, config, state, events),
        "position_monitor": PositionMonitor(broker, config, state, events),
        "emergency_exit": EmergencyExit(broker, config, state, events),
        "ratripal": Ratripal(broker, config, state, events),
    }

    # Always-on modules start immediately (position_monitor, emergency_exit)
    always_on = config.get("operations.always_on_modules", ["position_monitor", "emergency_exit"])
    for name in always_on:
        mod = modules.get(name)
        if mod and mod.is_enabled():
            mod.start()
            logger.info("Module started (always-on): %s", name)

    # 5. Build 3 PTB Applications
    #
    # Each build_application() sets up bot_data, registers command handlers,
    # and wires EventBus subscriptions.
    #
    # IMPORTANT: bot_data["loop"] is stored BEFORE the event subscriptions are
    # invoked (they fire lazily at runtime, not at registration time). This lets
    # sync EventBus callbacks (called from module threads) use
    # asyncio.run_coroutine_threadsafe(coro, app.bot_data["loop"]) safely.
    loop = asyncio.get_running_loop()

    from bat_telegram.bots.drishti import bot as drishti_bot
    from bat_telegram.bots.kavach import bot as kavach_bot
    from bat_telegram.bots.lakshmi import bot as lakshmi_bot
    from bat_telegram.incident_publisher import publish_incident, resolve_incident

    drishti_app = drishti_bot.build_application(
        broker=broker,
        client_code=client_code,
        state=state,
        event_bus=events,
    )
    kavach_app = kavach_bot.build_application(
        broker=broker,
        state=state,
        event_bus=events,
    )
    lakshmi_app = lakshmi_bot.build_application(broker=broker, state=state, event_bus=events)
    apps_by_name = {
        "drishti": drishti_app,
        "kavach": kavach_app,
        "lakshmi": lakshmi_app,
    }
    optional_apps: list[tuple[str, Any]] = []
    if _has_bot_secrets("sanchalak"):
        from bat_telegram.bots.sanchalak import bot as sanchalak_bot

        sanchalak_app = sanchalak_bot.build_application(
            state=state,
            event_bus=events,
            config=config,
        )
        apps_by_name["sanchalak"] = sanchalak_app
        optional_apps.append(("sanchalak", sanchalak_app))
    else:
        logger.info("SANCHALAK skipped — telegram/bots/sanchalak/token.env not present")

    if _has_bot_secrets("saransh"):
        from bat_telegram.bots.saransh import bot as saransh_bot

        saransh_app = saransh_bot.build_application(
            broker=broker,
            state=state,
            event_bus=events,
            config=config,
        )
        apps_by_name["saransh"] = saransh_app
        optional_apps.append(("saransh", saransh_app))
    else:
        logger.info("SARANSH skipped — telegram/bots/saransh/token.env not present")

    # Inject the running event loop + module map into every bot so that:
    # - sync EventBus callbacks can use run_coroutine_threadsafe(coro, loop)
    # - KAVACH /pause /resume /start_algo_now can start/stop module threads
    from core import utils as _u

    started_at_ist = _u.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    for app in [drishti_app, kavach_app, lakshmi_app, *(app for _, app in optional_apps)]:
        app.bot_data["loop"] = loop
        app.bot_data["modules"] = modules
        app.bot_data["apps"] = apps_by_name
        app.bot_data["started_at_ist"] = started_at_ist
        app.bot_data.setdefault("last_heartbeat_ist", started_at_ist)
        app.bot_data.setdefault("latest_error", "none")

    # 6. Initialize all apps (triggers post_init -> background coroutines start)
    apps = [drishti_app, kavach_app, lakshmi_app, *(app for _, app in optional_apps)]
    for app in apps:
        await app.initialize()
        await app.start()
        if app.updater is None:
            raise RuntimeError("Telegram application updater is unavailable")
        await app.updater.start_polling(drop_pending_updates=True)

    logger.info(
        "%d Telegram bots polling (%s)",
        len(apps),
        " | ".join(name.upper() for name in apps_by_name),
    )

    # 7. Startup notification via KAVACH (best-effort)
    async def _startup_notify() -> None:
        from core import utils as _u

        dep_files = sorted((Path(__file__).parent / "data" / "deployments").glob("batman_*.json"))
        deploy_str = f"ARMED ({dep_files[-1].name})" if dep_files else "idle - send /register"
        token_str = (
            "token valid" if not broker.needs_reauth() else "STALE - send fresh token to DRISHTI"
        )
        try:
            await kavach_app.bot.send_message(
                chat_id=kavach_app.bot_data["chat_id"],
                text=(
                    "Batman v3 online\n\n"
                    f"Started: {_u.now_ist().strftime('%H:%M IST, %d %b %Y')}\n"
                    f"Broker : {token_str}\n"
                    f"Deploy : {deploy_str}\n\n"
                    "Send /status for live module state."
                ),
            )
        except Exception as exc:
            logger.warning("Startup notify failed (non-critical): %s", exc)

    asyncio.create_task(_startup_notify())

    # 8. Lightweight background coroutines

    async def _token_age_monitor() -> None:
        """Warn every 30 min when broker token is past 20h safe window."""
        stale_reported = False
        while True:
            await asyncio.sleep(1800)
            if broker.needs_reauth():
                logger.warning(
                    "Broker token is stale (>20h). "
                    "Send a fresh Dhan access token to DRISHTI bot."
                )
                if not stale_reported:
                    stale_reported = True
                    await publish_incident(
                        source="drishti",
                        scenario="stale_token",
                        severity="major",
                        category="connectivity",
                        title="Broker token is stale",
                        error_message="Broker token is older than the 20h safe window and needs refresh.",
                        next_action="Send a fresh Dhan JWT to DRISHTI before the next trading action.",
                        source_bot=drishti_app.bot,
                        source_chat_id=str(drishti_app.bot_data["chat_id"]),
                    )
            elif stale_reported:
                stale_reported = False
                await resolve_incident(
                    source="drishti",
                    scenario="stale_token",
                    resolution_message="A fresh broker token is now active.",
                    source_bot=drishti_app.bot,
                    source_chat_id=str(drishti_app.bot_data["chat_id"]),
                )

    async def _heartbeat() -> None:
        """Log module + circuit state every 5 minutes."""
        from core.runtime_logging import drain_logging_failures

        reported_module_outages: set[str] = set()
        heartbeat_failed = False
        reported_logging_failures: set[str] = set()
        while True:
            await asyncio.sleep(300)
            try:
                running = [n for n, m in modules.items() if m.is_running]
                stopped = [n for n, m in modules.items() if m.is_enabled() and not m.is_running]
                logger.info(
                    "HEARTBEAT | running=%s | stopped=%s | circuit=%s | deployment=%s",
                    running or "none",
                    stopped or "none",
                    broker.circuit_status.get("state", "?"),
                    "armed" if state.get("deployment.confirmed") else "idle",
                )
                currently_offline_with_error: set[str] = set()
                for name in stopped:
                    err = getattr(modules[name], "_error", None)
                    if not err:
                        continue

                    currently_offline_with_error.add(name)
                    logger.warning("Module '%s' offline: %s", name, err)
                    if name in reported_module_outages:
                        continue

                    await publish_incident(
                        source="main",
                        scenario=f"module_offline_{name}",
                        severity="major",
                        category="runtime",
                        title=f"Module '{name}' is offline",
                        error_message=str(err),
                        next_action="Check module logs and restart/resume the algo module from KAVACH.",
                        source_bot=kavach_app.bot,
                        source_chat_id=str(kavach_app.bot_data["chat_id"]),
                    )
                    reported_module_outages.add(name)

                recovered = reported_module_outages - currently_offline_with_error
                for name in sorted(recovered):
                    await resolve_incident(
                        source="main",
                        scenario=f"module_offline_{name}",
                        resolution_message=f"Module '{name}' has recovered and is running again.",
                        source_bot=kavach_app.bot,
                        source_chat_id=str(kavach_app.bot_data["chat_id"]),
                    )
                    reported_module_outages.discard(name)

                sink_failures = drain_logging_failures()
                active_logging_failure_keys: set[str] = set()
                for item in sink_failures:
                    key = f"{item.sink}:{item.module}:{item.error}"
                    active_logging_failure_keys.add(key)
                    if key in reported_logging_failures:
                        continue

                    await publish_incident(
                        source="main",
                        scenario=f"logging_sink_failure_{item.sink}_{item.module}",
                        severity="critical",
                        category="runtime",
                        title=f"Runtime logging sink failure ({item.sink}:{item.module})",
                        error_message=item.error,
                        next_action="Check log folder permissions/path and disk availability.",
                        source_bot=kavach_app.bot,
                        source_chat_id=str(kavach_app.bot_data["chat_id"]),
                    )
                    reported_logging_failures.add(key)

                recovered_log_failures = reported_logging_failures - active_logging_failure_keys
                for key in sorted(recovered_log_failures):
                    parts = key.split(":", 2)
                    sink = parts[0]
                    module = parts[1]
                    await resolve_incident(
                        source="main",
                        scenario=f"logging_sink_failure_{sink}_{module}",
                        resolution_message=f"Runtime logging sink recovered ({sink}:{module}).",
                        source_bot=kavach_app.bot,
                        source_chat_id=str(kavach_app.bot_data["chat_id"]),
                    )
                    reported_logging_failures.discard(key)

                if heartbeat_failed:
                    heartbeat_failed = False
                    await resolve_incident(
                        source="main",
                        scenario="heartbeat_loop_error",
                        resolution_message="Main heartbeat loop recovered.",
                        source_bot=kavach_app.bot,
                        source_chat_id=str(kavach_app.bot_data["chat_id"]),
                    )
            except Exception as exc:
                heartbeat_failed = True
                logger.error("Heartbeat error: %s", exc)
                await publish_incident(
                    source="main",
                    scenario="heartbeat_loop_error",
                    severity="critical",
                    category="runtime",
                    title="Main heartbeat loop error",
                    error_message=str(exc),
                    next_action="Inspect main runtime logs and restart process if heartbeat remains unstable.",
                    source_bot=kavach_app.bot,
                    source_chat_id=str(kavach_app.bot_data["chat_id"]),
                )

    asyncio.create_task(_token_age_monitor())
    asyncio.create_task(_heartbeat())

    # 9. Shutdown handling
    stop_event = asyncio.Event()

    def _request_shutdown(*_) -> None:
        logger.info("Shutdown requested")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
    except NotImplementedError:
        # Windows does not support add_signal_handler for all signals
        signal.signal(signal.SIGINT, lambda *_: stop_event.set())
        signal.signal(signal.SIGTERM, lambda *_: stop_event.set())

    logger.info("=== BATMAN V3 ONLINE ===")

    # Block here until Ctrl+C or SIGTERM
    await stop_event.wait()

    # 10. Graceful shutdown
    logger.info("Graceful shutdown starting ...")

    for name, mod in modules.items():
        if mod.is_running:
            logger.info("Stopping module: %s", name)
            mod.stop()

    state.save()

    for app in reversed(apps):
        try:
            if app.updater is not None:
                await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as exc:
            logger.warning("Bot shutdown error: %s", exc)

    logger.info("=== BATMAN V3 OFFLINE ===")


# -- Entry point --------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(batman_main())
