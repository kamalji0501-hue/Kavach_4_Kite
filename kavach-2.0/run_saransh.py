#!/usr/bin/env python3
"""Run only the SARANSH Telegram bot (optional Phase 1 reporting)."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from telegram.error import NetworkError, TimedOut

from bat_telegram.bots.saransh.bot import apply_saransh_paths, build_application
from core.batman_mode import (
    access_token_path,
    ensure_runtime_layout,
    get_mode,
    log_root,
    prod_hostname_guard,
    saransh_lock_path,
    secrets_dhan_env_path,
    state_path,
)
from core.bot_health import start_health_heartbeat
from core.bot_instance_guard import bootstrap_exclusive_bot
from core.bot_launcher import warn_if_not_launched_via_bat
from core.bot_logging import configure_bot_logging
from core.broker_factory import apply_runtime_mode_provider, create_broker
from core.config import Config
from core.state import StateManager
from core.token_store import TokenStore

ROOT = Path(__file__).parent


def _configure_logging() -> None:
    configure_bot_logging(workspace_root=ROOT, bot_name="saransh")


def _dhan_env_path() -> Path:
    ext = secrets_dhan_env_path(ROOT)
    if ext.is_file():
        return ext
    return ROOT / "config" / ".env"


def _load_dhan_client_code() -> str:
    load_dotenv(_dhan_env_path())
    return os.environ.get("DHAN_CLIENT_CODE", "").strip()


def _load_config() -> Config:
    return Config.load_module_settings(
        settings_path=ROOT / "config" / "settings.json",
        env_path=_dhan_env_path(),
    )


def _connect_broker(client_code: str):
    if not client_code:
        return None

    token_store = TokenStore(path=access_token_path(ROOT))
    token, saved_at = token_store.load()
    if not token:
        return None
    if token_store.is_expired():
        logging.getLogger("run_saransh").warning(
            "Dhan token expired (saved_at=%s) — refresh via DRISHTI", saved_at
        )
        return None

    try:
        return create_broker(client_code, token, ROOT)
    except Exception as exc:
        logging.getLogger("run_saransh").error("Broker connect failed: %s", exc)
        return None


def main() -> None:
    _configure_logging()
    logger = logging.getLogger("run_saransh")
    ensure_runtime_layout(ROOT)
    mode = get_mode(ROOT)
    logger.info("Batman mode: %s | logs: %s", mode, log_root(ROOT))
    warn = prod_hostname_guard(ROOT)
    if warn:
        logger.warning(warn)

    apply_saransh_paths(ROOT)
    lock_path = saransh_lock_path(ROOT)
    warn_if_not_launched_via_bat("saransh")
    bootstrap_exclusive_bot("saransh", lock_path, logger, root=ROOT)

    start_health_heartbeat(ROOT, "saransh")

    client_code = _load_dhan_client_code()
    if not client_code:
        logger.warning("DHAN_CLIENT_CODE not set — orderbook/PnL sections may be empty")

    try:
        config = _load_config()
    except Exception as exc:
        logger.error("Config load failed: %s", exc)
        raise SystemExit(1) from exc

    broker = _connect_broker(client_code)
    if broker:
        logger.info("Broker connected — SARANSH orderbook/PnL sections enabled")
    else:
        logger.warning("No broker — summaries use deployment + telemetry only")

    state = StateManager(path=state_path(ROOT))
    if broker:
        apply_runtime_mode_provider(broker, state)

    restart_delay = 5
    session = 0
    while True:
        session += 1
        try:
            logger.info("Starting SARANSH Telegram bot (session %s)...", session)
            app = build_application(broker=broker, state=state, config=config)
            app.run_polling(drop_pending_updates=True)
            logger.warning("SARANSH polling exited — restarting in %ss", restart_delay)
        except KeyboardInterrupt:
            logger.info("SARANSH stopped by operator")
            return
        except (TimedOut, NetworkError) as exc:
            logger.warning(
                "Telegram network error: %s — restarting in %ss",
                exc,
                restart_delay,
            )
        except SystemExit:
            raise
        except Exception as exc:
            logger.error(
                "SARANSH crashed: %s — restarting in %ss",
                exc,
                restart_delay,
                exc_info=True,
            )
        time.sleep(restart_delay)


if __name__ == "__main__":
    main()
