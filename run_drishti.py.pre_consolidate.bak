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
    try:
        from core.dhan_credentials import apply_dhan_secrets_env

        apply_dhan_secrets_env(ROOT)
    except Exception:
        load_dotenv(_dhan_env_path())
    return __import__("os").environ.get("DHAN_CLIENT_CODE", "").strip() or (
        __import__("os").environ.get("DHAN_CLIENT_ID", "").strip()
    )


def _seed_token_store_from_env(token_store: TokenStore, logger: logging.Logger) -> None:
    """Seed TokenStore JWT from env: prefer DHAN_ACCESS_TOKEN, else PIN/TOTP.

    PIN/TOTP secrets are never written to disk — only the resulting daily JWT.
    """
    import os

    try:
        from core.dhan_credentials import apply_dhan_secrets_env

        apply_dhan_secrets_env(ROOT)
    except Exception:
        load_dotenv(_dhan_env_path())
    existing, _saved = token_store.load()
    if existing and not token_store.is_expired():
        return

    jwt = (os.environ.get("DHAN_ACCESS_TOKEN") or "").strip()
    if jwt:
        try:
            token_store.save(jwt)
            logger.info("Seeded Dhan JWT from DHAN_ACCESS_TOKEN into %s", token_store._path)
            return
        except Exception as exc:
            logger.warning("Could not seed Dhan JWT from DHAN_ACCESS_TOKEN: %s", exc)

    try:
        from core.dhan_pin_totp import obtain_access_token_via_pin_totp, pin_totp_env_present
    except Exception as exc:
        logger.debug("PIN/TOTP helper unavailable: %s", exc)
        return

    if not pin_totp_env_present():
        return
    try:
        _client, token = obtain_access_token_via_pin_totp()
        token_store.save(token)
        logger.info(
            "Seeded Dhan JWT via PIN/TOTP into %s (token_len=%s; PIN/TOTP not stored)",
            token_store._path,
            len(token),
        )
    except Exception as exc:
        logger.warning("PIN/TOTP token refresh failed: %s", exc)


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
            # Refresh shared + legacy together so Kavach 2.0 / consumers see the same saved_at.
            token_store.save(tok)
            legacy.save(tok)
        except Exception:
            pass
        logger.info("Valid Dhan token on disk — broker connects on first LTP/token action")
    else:
        logger.warning(
            "No valid token on disk — send JWT via Telegram or set DHAN_PIN+DHAN_TOTP_SECRET; LTP fetch will connect on demand"
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
