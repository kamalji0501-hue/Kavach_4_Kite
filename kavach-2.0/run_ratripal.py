#!/usr/bin/env python3
"""
Run only the RATRIPAL Telegram bot (standalone Phase 1).

Hosts the Ratripal Hedge Box module + HITL confirm/deny surface.
Connects to Dhan via the JWT saved by DRISHTI (data/access_token.json).
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from telegram.error import NetworkError, RetryAfter, TimedOut

from bat_telegram.bots.ratripal.bot import build_application
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
from modules.ratripal import Ratripal

ROOT = Path(__file__).parent

LOCK_PATH = bot_lock_path("ratripal", ROOT)

_RATRIPAL_MODULE: Ratripal | None = None
_TOKEN_WATCH_STOP: threading.Event | None = None


def _configure_logging() -> None:
    configure_bot_logging(workspace_root=ROOT, bot_name="ratripal")


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
            logging.getLogger("run_ratripal").warning(
                "Dhan token expired (saved_at=%s) — UAT ShadowBroker still loads fixture book; "
                "refresh JWT via DRISHTI for live LTP enrich",
                saved_at,
            )
        else:
            logging.getLogger("run_ratripal").warning(
                "Dhan token expired (saved_at=%s) — refresh via DRISHTI", saved_at
            )
            return None

    try:
        return create_broker(client_code, token, ROOT)
    except Exception as exc:
        logging.getLogger("run_ratripal").error("Broker connect failed: %s", exc)
        return None


def _sync_ratripal_enabled_from_deployment(state: StateManager) -> None:
    """Enable RATRIPAL when core sell legs exist (local sync; does not touch KAVACH2)."""
    logger = logging.getLogger("run_ratripal")
    path_raw = state.get("deployment.file")
    candidates: list[Path] = []
    if path_raw:
        candidates.append(Path(str(path_raw)))
    dep_dir = deployments_dir(ROOT)
    if dep_dir.is_dir():
        candidates.extend(sorted(dep_dir.glob("batman_*.json"), reverse=True)[:3])

    for path in candidates:
        if not path.is_file():
            continue
        try:
            dep = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("RATRIPAL enable sync skipped for %s: %s", path, exc)
            continue
        positions = dep.get("positions") or {}
        has_sell = bool(positions.get("pe_sell") or positions.get("ce_sell"))
        state.set("modules.ratripal.enabled", has_sell, save=False)
        if has_sell and not state.get("deployment.file"):
            state.set("deployment.file", str(path), save=False)
        if has_sell and not state.get("deployment.confirmed", False):
            # Prefer existing confirmed flag; do not force-confirm from file alone.
            pass
        state.save()
        logger.info(
            "RATRIPAL enable sync: modules.ratripal.enabled=%s (from %s)",
            has_sell,
            path.name,
        )
        return

    if not state.get("modules.ratripal.enabled", False):
        logger.info("RATRIPAL enable sync: no sell legs found — left disabled")


def _start_ratripal_module(
    broker,
    config: Config,
    state: StateManager,
    event_bus: EventBus,
) -> Ratripal | None:
    logger = logging.getLogger("run_ratripal")
    if broker is None:
        logger.warning("RATRIPAL module not started — no broker connection")
        return None

    mod = Ratripal(broker, config, state, event_bus)
    if not mod.is_enabled():
        logger.info("RATRIPAL disabled in config modules.ratripal.enabled — skipping")
        return None

    mod.start()
    logger.info(
        "RATRIPAL module started (deployment.confirmed=%s, state.enabled=%s, hedge_box.enabled=%s)",
        state.get("deployment.confirmed", False),
        state.get("modules.ratripal.enabled", False),
        config.get("hedge_box.enabled", False),
    )
    return mod


def _shutdown_ratripal() -> None:
    global _RATRIPAL_MODULE, _TOKEN_WATCH_STOP
    if _TOKEN_WATCH_STOP is not None:
        _TOKEN_WATCH_STOP.set()
        _TOKEN_WATCH_STOP = None
    if _RATRIPAL_MODULE is not None:
        logging.getLogger("run_ratripal").info("Stopping RATRIPAL module...")
        _RATRIPAL_MODULE.stop()
        _RATRIPAL_MODULE = None


def main() -> None:
    global _RATRIPAL_MODULE, _TOKEN_WATCH_STOP, LOCK_PATH

    _configure_logging()
    logger = logging.getLogger("run_ratripal")
    ensure_runtime_layout(ROOT)
    mode = get_mode(ROOT)
    logger.info("Batman mode: %s | logs: %s", mode, log_root(ROOT))
    warn = prod_hostname_guard(ROOT)
    if warn:
        logger.warning(warn)
    LOCK_PATH = bot_lock_path("ratripal", ROOT)
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

    warn_if_not_launched_via_bat("ratripal")
    bootstrap_exclusive_bot("ratripal", LOCK_PATH, logger, root=ROOT)
    atexit.register(_shutdown_ratripal)

    _health_state: dict = {"state": None}
    _runtime: dict = {"broker": None}

    def _ratripal_health() -> dict:
        st = _health_state.get("state")
        ok, detail = cache_consumer_status(path=default_cache_path())
        return {
            "deployment_confirmed": bool(st.get("deployment.confirmed")) if st else False,
            "ratripal_enabled": bool(st.get("modules.ratripal.enabled")) if st else False,
            "pending_request": bool(st.get("ratripal.pending.request_id")) if st else False,
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
    _sync_ratripal_enabled_from_deployment(state)

    def _bootstrap_from_token(token: str) -> None:
        global _RATRIPAL_MODULE
        if _runtime["broker"] is not None:
            return
        if not client_code:
            return
        try:
            boot_broker = create_broker(client_code, token, ROOT)
        except Exception as exc:
            logger.error("RATRIPAL broker bootstrap failed: %s", exc)
            return
        _runtime["broker"] = boot_broker
        apply_runtime_mode_provider(boot_broker, state)
        logger.info("RATRIPAL broker bootstrapped from token file")
        if _RATRIPAL_MODULE is None:
            _RATRIPAL_MODULE = _start_ratripal_module(boot_broker, config, state, event_bus)

    broker = _connect_broker(client_code)
    _runtime["broker"] = broker
    if broker:
        if mode == "uat":
            logger.info("UAT ShadowBroker ready")
        else:
            logger.info("Broker connected")
    else:
        logger.warning(
            "No broker at startup — will bootstrap when DRISHTI saves a valid JWT"
        )

    start_health_heartbeat(ROOT, "ratripal", extra_provider=_ratripal_health)

    if broker:
        apply_runtime_mode_provider(broker, state)
        _RATRIPAL_MODULE = _start_ratripal_module(broker, config, state, event_bus)

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
            logger.info("Starting RATRIPAL Telegram bot (session %s)...", session)
            app = build_application(
                broker=_runtime["broker"],
                state=state,
                event_bus=event_bus,
                config=config,
            )
            # Keep queued operator messages (e.g. hi /start) after downtime.
            app.run_polling(drop_pending_updates=False)
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(None, failure_streak=failure_streak)
            logger.warning("RATRIPAL polling exited — restarting in %.1fs", restart_delay)
        except KeyboardInterrupt:
            logger.info("RATRIPAL stopped by operator")
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
                "RATRIPAL crashed: %s — restarting in %.1fs",
                exc,
                restart_delay,
                exc_info=True,
            )
        time.sleep(restart_delay)


if __name__ == "__main__":
    main()
