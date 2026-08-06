#!/usr/bin/env python3
"""Run only the GO Telegram bot (independent — not Phase 1)."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telegram.error import NetworkError, RetryAfter, TimedOut

from bat_telegram.loader import load_bot_config
from GO.bot import build_application
from GO.strategy.single_leg import SingleLegMonitor
from core.batman_mode import (
    access_token_path,
    bot_lock_path,
    ensure_runtime_layout,
    get_mode,
    log_root,
    prod_hostname_guard,
    secrets_dhan_env_path,
    state_path,
)
from core.bot_health import start_health_heartbeat
from core.bot_instance_guard import bootstrap_exclusive_bot
from core.bot_launcher import warn_if_not_launched_via_bat
from core.bot_logging import configure_bot_logging
from core.broker_factory import apply_runtime_mode_provider, create_broker
from core.state import StateManager
from core.token_store import TokenStore
from core.token_watch import start_token_watch

ROOT = Path(__file__).parent
LOCK_PATH = bot_lock_path("go", ROOT)


def _configure_logging() -> None:
    configure_bot_logging(workspace_root=ROOT, bot_name="go")


def _dhan_env_path() -> Path:
    ext = secrets_dhan_env_path(ROOT)
    if ext.is_file():
        return ext
    return ROOT / "config" / ".env"


def _load_dhan_client_code() -> str:
    load_dotenv(_dhan_env_path())
    return os.environ.get("DHAN_CLIENT_CODE", "").strip()


def _connect_broker(client_code: str, logger: logging.Logger):
    if not client_code:
        return None
    token_store = TokenStore(path=access_token_path(ROOT))
    token, saved_at = token_store.load()
    if not token:
        return None
    if token_store.is_expired():
        logger.warning("Dhan token expired (saved_at=%s) — refresh via DRISHTI", saved_at)
        return None
    try:
        return create_broker(client_code, token, ROOT)
    except Exception as exc:
        logger.error("Broker connect failed: %s", exc)
        return None


def main() -> None:
    _configure_logging()
    logger = logging.getLogger("run_go")
    ensure_runtime_layout(ROOT)
    mode = get_mode(ROOT)
    logger.info("Batman mode: %s | logs: %s | GO independent (not Phase 1)", mode, log_root(ROOT))
    warn = prod_hostname_guard(ROOT)
    if warn:
        logger.warning(warn)

    warn_if_not_launched_via_bat("go")
    bootstrap_exclusive_bot("go", LOCK_PATH, logger, root=ROOT)
    start_health_heartbeat(ROOT, "go")

    cfg = load_bot_config("go")
    params = cfg.params
    client_code = _load_dhan_client_code()
    if not client_code:
        logger.warning("DHAN_CLIENT_CODE not set — order placement disabled until set")

    state = StateManager(path=state_path(ROOT))
    broker = _connect_broker(client_code, logger)
    if broker:
        apply_runtime_mode_provider(broker, state)
        logger.info("Broker connected for GO")
    else:
        logger.warning("No broker — Telegram UI up; place orders after DRISHTI JWT")

    chat_id = cfg.chat_id
    notify_holder: dict[str, Any] = {"app": None}

    def _notify(msg: str) -> None:
        app = notify_holder.get("app")
        if not app or not chat_id:
            logger.info("GO notify (no app yet): %s", msg)
            return
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    app.bot.send_message(chat_id=chat_id, text=msg), loop
                )
            else:
                logger.info("GO notify: %s", msg)
        except Exception as exc:
            logger.warning("GO notify failed: %s", exc)

    monitor = SingleLegMonitor(
        broker,
        params=params,
        root=ROOT,
        notify=_notify,
        poll_seconds=float(params.get("single_leg_poll_seconds", 3.0)),
    )
    if broker:
        monitor.start()

    token_stop = None
    if client_code:

        def _on_token(token: str) -> None:
            nonlocal broker
            try:
                broker = create_broker(client_code, token, ROOT)
                apply_runtime_mode_provider(broker, state)
                monitor.broker = broker
                monitor.start()
                logger.info("GO broker hot-reloaded from TokenStore")
            except Exception as exc:
                logger.error("GO token bootstrap failed: %s", exc)

        token_stop = start_token_watch(
            broker,
            client_code=client_code,
            token_path=access_token_path(ROOT),
            on_token_ready=_on_token if broker is None else None,
        )

    from telegram.error import Conflict as _TGConflict

    _MAX_CONFLICT_RETRIES = 5
    _conflict_attempts = 0
    try:
        while _conflict_attempts <= _MAX_CONFLICT_RETRIES:
            try:
                logger.info("Starting GO (attempt %s)...", _conflict_attempts + 1)
                app = build_application(
                    broker=broker,
                    workspace_root=ROOT,
                    single_leg_monitor=monitor,
                )
                notify_holder["app"] = app
                app.run_polling(drop_pending_updates=True, timeout=25)
                break
            except KeyboardInterrupt:
                logger.info("GO stopped by operator")
                break
            except SystemExit:
                raise
            except _TGConflict as exc:
                _conflict_attempts += 1
                if _conflict_attempts > _MAX_CONFLICT_RETRIES:
                    logger.error(
                        "GO Conflict persists after %s retries — exiting",
                        _MAX_CONFLICT_RETRIES,
                    )
                    raise SystemExit(1)
                logger.warning(
                    "GO Telegram Conflict (attempt %s/%s) — waiting 25s: %s",
                    _conflict_attempts,
                    _MAX_CONFLICT_RETRIES,
                    exc,
                )
                time.sleep(25)
            except (RetryAfter, TimedOut, NetworkError) as exc:
                logger.warning("Telegram network error: %s — exiting for systemd restart", exc)
                raise SystemExit(1)
            except Exception as exc:
                logger.error("GO crashed: %s", exc, exc_info=True)
                raise SystemExit(1)
    finally:
        monitor.stop()
        if token_stop is not None:
            token_stop.set()


if __name__ == "__main__":
    main()
