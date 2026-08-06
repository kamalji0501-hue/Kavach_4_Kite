#!/usr/bin/env python3
"""
Run only the KAVACH Telegram bot (standalone Phase 1).

Connects to Dhan via the JWT saved by DRISHTI (data/access_token.json).
Starts ATO Protection module in a background thread when broker + config allow.

Requires DRISHTI REST NIFTY feed running for LTP cache during market hours.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from telegram.error import NetworkError, RetryAfter, TimedOut

from bat_telegram.bots.kavach.bot import build_application
from core.batman_mode import (
    access_token_path,
    bot_lock_path,
    deployments_dir,
    ensure_runtime_layout,
    get_mode,
    log_root,
    prod_hostname_guard,
    state_path,
)
from core.bot_health import start_health_heartbeat
from core.bot_instance_guard import bootstrap_exclusive_bot
from core.bot_launcher import warn_if_not_launched_via_bat
from core.bot_logging import configure_bot_logging
from core.broker_factory import apply_runtime_mode_provider, create_broker
from core.config import Config
from core.event_bus import EventBus
from core.nifty_ltp_feed import cache_consumer_status, default_cache_path
from core.telegram_runtime import PollingRestartPolicy
from core.state import StateManager
from core.token_store import TokenStore
from core.token_watch import start_token_watch
from core.daily_ato_prompt import daily_ato_prompt_status_line
from modules.ato_protection import ATOProtection, apply_ato_analytics_paths

ROOT = Path(__file__).parent

import bat_telegram.bots.kavach.bot as _kavach_bot

LOCK_PATH = bot_lock_path("kavach", ROOT)

_ATO_MODULE: ATOProtection | None = None
_TOKEN_WATCH_STOP: threading.Event | None = None


def _configure_logging() -> None:
    configure_bot_logging(workspace_root=ROOT, bot_name="kavach")
    try:
        from core.money_audit import audit
        audit("kavach.boot", runner=str(Path(__file__).name), root=str(ROOT))
    except Exception:
        pass


def _load_dhan_client_code() -> str:
    load_dotenv(ROOT / "config" / ".env")
    return os.environ.get("DHAN_CLIENT_CODE", "").strip()


def _load_config() -> Config:
    return Config.load_module_settings(
        settings_path=ROOT / "config" / "settings.json",
        env_path=ROOT / "config" / ".env",
    )


def _connect_broker(client_code: str):
    if not client_code:
        return None

    token_store = TokenStore(path=access_token_path(ROOT))
    token, saved_at = token_store.load()
    if not token:
        return None
    if token_store.is_effectively_expired():
        mode = get_mode(ROOT)
        if mode == "uat":
            logging.getLogger("run_kavach").warning(
                "Dhan token expired (saved_at=%s) — UAT ShadowBroker still loads fixture book; "
                "refresh JWT via DRISHTI for live LTP enrich",
                saved_at,
            )
        else:
            logging.getLogger("run_kavach").warning(
                "Dhan token expired (saved_at=%s) — refresh via DRISHTI", saved_at
            )
            return None

    try:
        return create_broker(client_code, token, ROOT)
    except Exception as exc:
        logging.getLogger("run_kavach").error("Broker connect failed: %s", exc)
        return None


def _apply_mode_paths() -> None:
    """Point KAVACH deployments/state at data/{mode}/."""
    dep = deployments_dir(ROOT)
    dep.mkdir(parents=True, exist_ok=True)
    (dep / "archive").mkdir(parents=True, exist_ok=True)
    _kavach_bot._DEPLOY_DIR = dep
    _kavach_bot._ARCHIVE_DIR = dep / "archive"
    _kavach_bot._DEPLOY_LOG = dep / "deploy_log.jsonl"
    apply_ato_analytics_paths(ROOT)


def _start_ato_module(
    broker,
    config: Config,
    state: StateManager,
    event_bus: EventBus,
) -> ATOProtection | None:
    """Start ATO Protection daemon thread (Phase 1 standalone)."""
    logger = logging.getLogger("run_kavach")
    if broker is None:
        logger.warning("ATO not started — no broker connection")
        return None

    ato = ATOProtection(broker, config, state, event_bus)
    if not ato.is_enabled():
        logger.info("ATO Protection disabled in config — skipping module start")
        return None

    # Order sink: paper → OrderManager/FakeBroker; live → real broker (no paper OM).
    # Prefer deployment/state order_mode from last /register; ORDER_MODE env overrides.
    try:
        import os

        from core.order_mode import (
            configure_ato_order_sink,
            latest_deployment_order_mode,
            normalize_order_mode,
            order_mode_from_state,
        )

        env_mode = (os.environ.get("ORDER_MODE") or "").strip().lower()
        if env_mode in {"paper", "live"}:
            order_mode = env_mode
        else:
            order_mode = order_mode_from_state(state, default=latest_deployment_order_mode(ROOT))
        order_mode = normalize_order_mode(order_mode)
        configure_ato_order_sink(ato, order_mode=order_mode, workspace_root=ROOT, state=state)
        logger.info("ATO order sink configured mode=%s", order_mode)
        try:
            from core.money_audit import audit

            audit("kavach.order_sink.ready", mode=order_mode, runner="run_kavach")
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Order sink not configured: %s", exc)

    ato.start()
    logger.info(
        "ATO Protection module started (deployment.confirmed=%s, algo.paused=%s)",
        state.get("deployment.confirmed", False),
        state.get("algo.paused", False),
    )
    return ato


def _shutdown_ato() -> None:
    global _ATO_MODULE, _TOKEN_WATCH_STOP
    if _TOKEN_WATCH_STOP is not None:
        _TOKEN_WATCH_STOP.set()
        _TOKEN_WATCH_STOP = None
    if _ATO_MODULE is not None:
        logging.getLogger("run_kavach").info("Stopping ATO Protection module...")
        _ATO_MODULE.stop()
        _ATO_MODULE = None


def main() -> None:
    global _ATO_MODULE, _TOKEN_WATCH_STOP

    _configure_logging()
    logger = logging.getLogger("run_kavach")
    ensure_runtime_layout(ROOT)
    mode = get_mode(ROOT)
    logger.info("Batman mode: %s | logs: %s", mode, log_root(ROOT))
    logger.info(daily_ato_prompt_status_line(ROOT))
    warn = prod_hostname_guard(ROOT)
    if warn:
        logger.warning(warn)
    _apply_mode_paths()
    global LOCK_PATH
    LOCK_PATH = bot_lock_path("kavach", ROOT)
    ensure_runtime_layout(ROOT)

    if mode == "uat":
        try:
            from core.uat_ingest import ingest_uat_at_startup

            result = ingest_uat_at_startup(ROOT)
            if result.get("ok"):
                logger.info("UAT startup ingest: %s", result.get("image"))
            elif result.get("skipped"):
                logger.info("UAT startup ingest skipped: %s", result.get("reason"))
            else:
                logger.warning("UAT startup ingest: %s", result.get("error"))
        except Exception as exc:
            logger.warning("UAT startup ingest failed: %s", exc)
    warn_if_not_launched_via_bat("kavach")
    bootstrap_exclusive_bot("kavach", LOCK_PATH, logger, root=ROOT)
    atexit.register(_shutdown_ato)

    _health_state: dict = {"state": None}
    _runtime: dict = {"broker": None}

    def _kavach_health() -> dict:
        st = _health_state.get("state")
        ok, detail = cache_consumer_status(path=default_cache_path())
        return {
            "deployment_confirmed": bool(st.get("deployment.confirmed")) if st else False,
            "ce_ato_active": bool(st.get("ato.ce_ato_active")) if st else False,
            "pe_ato_active": bool(st.get("ato.pe_ato_active")) if st else False,
            "nifty_cache_ready": ok,
            "nifty_cache_detail": detail,
            "broker_connected": _runtime["broker"] is not None,
        }

    client_code = _load_dhan_client_code()
    if not client_code:
        logger.warning("DHAN_CLIENT_CODE not set in config/.env")

    try:
        config = _load_config()
    except Exception as exc:
        logger.error("Config load failed: %s", exc)
        raise SystemExit(1) from exc

    state = StateManager(path=state_path(ROOT))
    _health_state["state"] = state
    event_bus = EventBus()

    def _bootstrap_from_token(token: str) -> None:
        global _ATO_MODULE
        if _runtime["broker"] is not None:
            return
        if not client_code:
            return
        try:
            boot_broker = create_broker(client_code, token, ROOT)
        except Exception as exc:
            logger.error("KAVACH broker bootstrap failed: %s", exc)
            return
        _runtime["broker"] = boot_broker
        apply_runtime_mode_provider(boot_broker, state)
        logger.info("KAVACH broker bootstrapped from token file")
        if _ATO_MODULE is None:
            _ATO_MODULE = _start_ato_module(boot_broker, config, state, event_bus)

    broker = _connect_broker(client_code)
    _runtime["broker"] = broker
    if broker:
        if mode == "uat":
            logger.info("UAT ShadowBroker ready — /positions from screenshot book")
        else:
            logger.info("Broker connected — /positions and /register ready")
    else:
        logger.warning(
            "No broker at startup — will bootstrap when DRISHTI saves a valid JWT"
        )

    start_health_heartbeat(ROOT, "kavach", extra_provider=_kavach_health)
    if state.get("deployment.confirmed", False):
        logger.info(
            "KAVACH session restore: deployment.confirmed=True ce_ato=%s pe_ato=%s",
            state.get("ato.ce_ato_active", False),
            state.get("ato.pe_ato_active", False),
        )
    else:
        logger.info("KAVACH session restore: no confirmed deployment — tap Register when ready")

    if broker:
        apply_runtime_mode_provider(broker, state)
        _ATO_MODULE = _start_ato_module(broker, config, state, event_bus)

    _TOKEN_WATCH_STOP = start_token_watch(
        _runtime["broker"],
        client_code=client_code,
        token_path=access_token_path(ROOT),
        on_token_ready=_bootstrap_from_token,
    )

    restart_policy = PollingRestartPolicy()
    session = 0
    failure_streak = 0
    while True:
        session += 1
        try:
            logger.info("Starting KAVACH Telegram bot (session %s)...", session)
            app = build_application(
                broker=_runtime["broker"], state=state, event_bus=event_bus
            )
            app.run_polling(drop_pending_updates=True)
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(None, failure_streak=failure_streak)
            logger.warning("KAVACH polling exited — restarting in %.1fs", restart_delay)
        except KeyboardInterrupt:
            logger.info("KAVACH stopped by operator")
            return
        except (RetryAfter, TimedOut, NetworkError) as exc:
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(exc, failure_streak=failure_streak)
            logger.warning(
                "Telegram network error: %s — restarting in %.1fs",
                exc,
                restart_delay,
            )
        except SystemExit:
            raise
        except Exception as exc:
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(exc, failure_streak=failure_streak)
            logger.error(
                "KAVACH crashed: %s — restarting in %.1fs",
                exc,
                restart_delay,
                exc_info=True,
            )
        time.sleep(restart_delay)


if __name__ == "__main__":
    main()
