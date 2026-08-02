#!/usr/bin/env python3
"""
Run only the DRISHTI Telegram bot.

Use this first when setting up Telegram, before starting the full Batman
orchestrator in main.py.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from dotenv import load_dotenv
from telegram.error import NetworkError, RetryAfter, TimedOut

from bat_telegram.bots.drishti.bot import build_application
from core.bot_health import start_health_heartbeat
from core.bot_instance_guard import bootstrap_exclusive_bot
from core.bot_launcher import warn_if_not_launched_via_bat
from core.bot_logging import configure_bot_logging
from core.nifty_ltp_feed import cache_consumer_status, default_cache_path
from core.telegram_runtime import PollingRestartPolicy
from core.token_store import TokenStore

from core.batman_mode import access_token_path, bot_lock_path, ensure_runtime_layout, secrets_dhan_env_path

ROOT = Path(__file__).parent
LOCK_PATH = bot_lock_path("drishti", ROOT)


def _dhan_env_path() -> Path:
    ext = secrets_dhan_env_path(ROOT)
    if ext.is_file():
        return ext
    return ROOT / "config" / ".env"


def _configure_logging() -> None:
    configure_bot_logging(workspace_root=ROOT, bot_name="drishti")


def _load_dhan_client_code() -> str:
    """Load broker client code without requiring full Batman config."""
    load_dotenv(_dhan_env_path())
    return __import__("os").environ.get("DHAN_CLIENT_CODE", "").strip()


def _seed_token_store_from_env(token_store: TokenStore, logger: logging.Logger) -> None:
    """If JWT is in config/.env but not yet on disk, persist it once for DRISHTI/ATO."""
    import os

    load_dotenv(_dhan_env_path())
    jwt = (os.environ.get("DHAN_ACCESS_TOKEN") or "").strip()
    if not jwt:
        return
    existing, _saved = token_store.load()
    if existing and not token_store.is_expired():
        return
    try:
        token_store.save(jwt)
        logger.info("Seeded Dhan JWT from config/.env into %s", token_store._path)
    except Exception as exc:
        logger.warning("Could not seed Dhan JWT from env: %s", exc)


def main() -> None:
    _configure_logging()
    logger = logging.getLogger("run_drishti")
    ensure_runtime_layout(ROOT)
    warn_if_not_launched_via_bat("drishti")
    bootstrap_exclusive_bot("drishti", LOCK_PATH, logger, root=ROOT)

    def _drishti_health() -> dict:
        ok, detail = cache_consumer_status(path=default_cache_path())
        return {"nifty_cache_ready": ok, "nifty_cache_detail": detail}

    start_health_heartbeat(ROOT, "drishti", extra_provider=_drishti_health)

    client_code = _load_dhan_client_code()
    if not client_code:
        logger.warning(
            "DHAN_CLIENT_CODE not set in config/.env — "
            "broker/LTP features need this; Telegram bot will still start"
        )

    token_store = TokenStore(path=access_token_path(ROOT))
    _seed_token_store_from_env(token_store, logger)
    # Keep legacy path in sync for older helpers that still read data/access_token.json
    legacy = TokenStore(path=ROOT / "data" / "access_token.json")
    tok, _ = token_store.load()
    if tok and not token_store.is_expired():
        try:
            legacy.save(tok)
        except Exception:
            pass
        logger.info("Valid Dhan token on disk — broker connects on first LTP/token action")
    else:
        logger.warning(
            "No valid token on disk — send JWT via Telegram; LTP fetch will connect on demand"
        )

    restart_policy = PollingRestartPolicy()
    crash_attempt = 0
    failure_streak = 0
    while True:
        app = None
        try:
            crash_attempt += 1
            logger.info("Starting DRISHTI Telegram bot (session %s)...", crash_attempt)
            app = build_application(client_code=client_code)
            app.run_polling(drop_pending_updates=True)
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(None, failure_streak=failure_streak)
            logger.warning("DRISHTI polling exited — restarting in %.1fs", restart_delay)
        except KeyboardInterrupt:
            logger.info("DRISHTI stopped by operator")
            return
        except (RetryAfter, TimedOut, NetworkError) as exc:
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(exc, failure_streak=failure_streak)
            logger.warning("Telegram network error: %s — restarting in %.1fs", exc, restart_delay)
        except SystemExit:
            raise
        except Exception as exc:
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(exc, failure_streak=failure_streak)
            logger.error("DRISHTI crashed: %s — restarting in %.1fs", exc, restart_delay, exc_info=True)
        time.sleep(restart_delay)


if __name__ == "__main__":
    main()
