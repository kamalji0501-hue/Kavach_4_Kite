#!/usr/bin/env python3
"""
Run only the DRISHTI Telegram bot.

Use this first when setting up Telegram, before starting the full Batman
orchestrator in main.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from bat_telegram.bots.drishti.bot import build_application
from core.bot_health import start_health_heartbeat
from core.bot_instance_guard import bootstrap_exclusive_bot
from core.bot_launcher import warn_if_not_launched_via_bat
from core.bot_logging import configure_bot_logging
from core.nifty_ltp_feed import cache_consumer_status, default_cache_path
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

    # Shared TOTP: refresh JWT before app start when needed.
    try:
        from core import dhan_totp as _dhan_totp

        if client_code and _dhan_totp.load_credentials(ROOT).configured:
            if _dhan_totp.needs_refresh(ROOT) and _dhan_totp.is_auto_renew_enabled(ROOT):
                logger.info("DRISHTI TOTP bootstrap: refreshing JWT")
                _dhan_totp.renew_and_save(ROOT)
    except Exception as exc:
        logger.warning("DRISHTI TOTP bootstrap skipped: %s", exc)

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
            "No valid token on disk — send JWT via Telegram; LTP fetch will connect on demand"
        )

    totp_holder: dict[str, Any] = {"renewer": None, "app": None, "loop": None}

    def _apply_totp_token(token: str) -> None:
        """Hot-reload broker + restart NIFTY feed after background TOTP renew.

        Feed restart must run on PTB's event-loop thread (not the renewer thread).
        """
        app = totp_holder.get("app")
        if app is None:
            logger.info("DRISHTI TOTP applied to TokenStore (app not ready yet)")
            return

        def _broker_reload() -> None:
            code = str(app.bot_data.get("client_code") or client_code or "").strip()
            broker = app.bot_data.get("broker")
            if broker is not None and code and hasattr(broker, "hot_reload_token"):
                broker.hot_reload_token(code, token)
            elif code:
                from core.broker import BatmanBroker

                app.bot_data["broker"] = BatmanBroker.connect_with_token(code, token)
                app.bot_data.setdefault("client_code", code)

        def _restart_feed() -> None:
            from bat_telegram.bots.drishti.nifty_feed_integration import (
                ensure_default_feed_config,
                restart_nifty_feed,
            )

            try:
                _broker_reload()
                params = app.bot_data.get("params") or {}
                ensure_default_feed_config(params)
                restart_nifty_feed(app, TokenStore(path=access_token_path(ROOT)))
                logger.info("DRISHTI TOTP applied JWT to broker + NIFTY feed")
            except Exception as exc:
                logger.error("DRISHTI TOTP apply failed: %s", exc)

        try:
            loop = totp_holder.get("loop")
            if loop is not None and getattr(loop, "is_running", lambda: False)():
                loop.call_soon_threadsafe(_restart_feed)
                return
            # App up but loop not captured yet — broker only.
            _broker_reload()
            logger.warning(
                "DRISHTI TOTP: JWT applied to broker; feed restart deferred (no main loop yet)"
            )
        except Exception as exc:
            logger.error("DRISHTI TOTP apply failed: %s", exc)

    try:
        from core import dhan_totp as _dhan_totp

        totp_renewer = _dhan_totp.TotpRenewer(ROOT, on_token=_apply_totp_token)
        totp_renewer.start()
        totp_holder["renewer"] = totp_renewer
    except Exception as exc:
        logger.warning("DRISHTI TOTP renewer not started: %s", exc)

    # Single-shot run — systemd Restart=on-failure handles restarts on Linux server.
    # Retries Conflict up to 3 times (Telegram stale session lasts ~30-60s after kill).
    from telegram.error import Conflict as _TGConflict

    _MAX_CONFLICT_RETRIES = 3
    _conflict_attempts = 0
    while _conflict_attempts <= _MAX_CONFLICT_RETRIES:
        try:
            logger.info("Starting DRISHTI Telegram bot (attempt %s)...", _conflict_attempts + 1)
            app = build_application(client_code=client_code)
            app.bot_data["workspace_root"] = ROOT
            if totp_holder.get("renewer") is not None:
                app.bot_data["totp_renewer"] = totp_holder["renewer"]
            totp_holder["app"] = app

            prev_post_init = app.post_init

            async def _post_init(application) -> None:
                totp_holder["loop"] = asyncio.get_running_loop()
                logger.info("DRISHTI TOTP main loop captured for renewer callbacks")
                if prev_post_init is not None:
                    await prev_post_init(application)

            app.post_init = _post_init
            app.run_polling(drop_pending_updates=True, timeout=25)
            break
        except KeyboardInterrupt:
            logger.info("DRISHTI stopped by operator")
            break
        except SystemExit:
            raise
        except _TGConflict as exc:
            _conflict_attempts += 1
            if _conflict_attempts > _MAX_CONFLICT_RETRIES:
                logger.error("DRISHTI Conflict persists after %s retries — exiting", _MAX_CONFLICT_RETRIES)
                raise SystemExit(1)
            logger.warning(
                "DRISHTI Telegram Conflict (attempt %s/%s) — waiting 25s: %s",
                _conflict_attempts, _MAX_CONFLICT_RETRIES, exc,
            )
            time.sleep(25)
        except Exception as exc:
            logger.error("DRISHTI crashed: %s", exc, exc_info=True)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
