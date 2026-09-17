#!/usr/bin/env python3
"""
Run only the KAVACH Telegram bot (standalone Phase 1).

Connects to Zerodha via Kite REST (feeder session / TOKEN Zerodha paste).
Starts ATO Protection in a background thread when broker + config allow.

NIFTY LTP comes from Datafeedbot (Feeder) cache/IPC — not Drishti.
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

from bat_telegram.bots.kavach2.bot import build_application
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
from core.feeder_nifty_collector import stop_feeder_nifty_collector
from modules.ato_protection import ATOProtection, apply_ato_analytics_paths
from modules.ratripal import Ratripal

ROOT = Path(__file__).parent

import bat_telegram.bots.kavach2.bot as _kavach_bot

LOCK_PATH = bot_lock_path("kavach2", ROOT)

_ATO_MODULE: ATOProtection | None = None
_RATRIPAL_MODULE: Ratripal | None = None
_TOKEN_WATCH_STOP: threading.Event | None = None


def _telegram_disabled() -> bool:
    return (os.environ.get("KAVACH2_TELEGRAM_DISABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _configure_logging() -> None:
    configure_bot_logging(workspace_root=ROOT, bot_name="kavach2")


def _load_dhan_client_code() -> str:
    load_dotenv(ROOT / "config" / ".env")
    return os.environ.get("DHAN_CLIENT_CODE", "").strip()


def _load_config() -> Config:
    return Config.load_module_settings(
        settings_path=ROOT / "config" / "settings.json",
        env_path=ROOT / "config" / ".env",
    )


def _connect_broker(client_code: str):
    mode = get_mode(ROOT)
    logger = logging.getLogger("run_kavach")
    if mode == "uat":
        token_store = TokenStore(path=access_token_path(ROOT))
        token, saved_at = token_store.load()
        try:
            return create_broker(client_code or "uat", token or "uat", ROOT)
        except Exception as exc:
            logger.error("UAT broker connect failed: %s", exc)
            return None
    try:
        return create_broker(client_code or "", "", ROOT)
    except Exception as exc:
        logger.error("Zerodha broker connect failed: %s", exc)
        try:
            from core.desk_alerts import emit_desk_alert

            emit_desk_alert(
                severity="red",
                category="Tokens",
                alert="Kavach started with no Kite token — live orders cannot go out.",
                log=f"Zerodha broker connect failed: {exc}",
            )
        except Exception:
            pass
        return None


def _apply_mode_paths() -> None:
    """Point KAVACH 2.0 deployments/state at data/{mode}/."""
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
            default_mode = "live" if get_mode(ROOT) == "prod" else latest_deployment_order_mode(ROOT)
            order_mode = order_mode_from_state(state, default=default_mode)
        order_mode = normalize_order_mode(order_mode)
        configure_ato_order_sink(ato, order_mode=order_mode, workspace_root=ROOT, state=state)
        logger.info("ATO order sink configured mode=%s", order_mode)
        try:
            from core.money_audit import audit

            audit("kavach.order_sink.ready", mode=order_mode, runner="run_kavach2")
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




def _sync_ratripal_enabled_from_deployment(state: StateManager) -> None:
    """Enable Hedge Box / overnight when registered sell legs exist."""
    logger = logging.getLogger("run_kavach")
    path_raw = state.get("deployment.file")
    has_sell = False
    if path_raw:
        try:
            import json as _json
            from pathlib import Path as _P

            dep = _json.loads(_P(str(path_raw)).read_text(encoding="utf-8"))
            positions = dep.get("positions") or {}
            has_sell = bool(positions.get("pe_sell") or positions.get("ce_sell"))
        except Exception as exc:
            logger.warning("RATRIPAL enable sync failed: %s", exc)
    if not has_sell:
        # Fall back to live state legs (register already confirmed).
        try:
            has_sell = bool(state.get("positions.pe_sell") or state.get("positions.ce_sell"))
        except Exception:
            has_sell = False
    state.set("modules.ratripal.enabled", bool(has_sell), save=False)
    try:
        state.save()
    except Exception:
        pass
    logger.info("RATRIPAL enable sync: modules.ratripal.enabled=%s", bool(has_sell))


def _start_ratripal_module(
    broker,
    config: Config,
    state: StateManager,
    event_bus: EventBus,
) -> Ratripal | None:
    """Start Hedge Box / overnight (RATRIPAL) daemon thread beside ATO."""
    logger = logging.getLogger("run_kavach")
    if broker is None:
        logger.warning("RATRIPAL not started — no broker connection")
        return None
    _sync_ratripal_enabled_from_deployment(state)
    if not bool(config.get("hedge_box.enabled", True)):
        logger.info("RATRIPAL skipped — hedge_box.enabled=false")
        return None
    if not bool(config.get("modules.ratripal.enabled", True)):
        logger.info("RATRIPAL skipped — modules.ratripal.enabled=false")
        return None
    mod = Ratripal(broker, config, state, event_bus)
    if not mod.is_enabled():
        logger.info("RATRIPAL disabled in config — skipping module start")
        return None
    mod.start()
    logger.info(
        "RATRIPAL / overnight hedge started (deployment.confirmed=%s, hedge_box.enabled=%s)",
        state.get("deployment.confirmed", False),
        config.get("hedge_box.enabled", False),
    )
    return mod

def _shutdown_ato() -> None:
    global _ATO_MODULE, _RATRIPAL_MODULE, _TOKEN_WATCH_STOP
    stop_feeder_nifty_collector()
    if _TOKEN_WATCH_STOP is not None:
        _TOKEN_WATCH_STOP.set()
        _TOKEN_WATCH_STOP = None
    if _RATRIPAL_MODULE is not None:
        logging.getLogger("run_kavach").info("Stopping RATRIPAL / overnight hedge...")
        _RATRIPAL_MODULE.stop()
        _RATRIPAL_MODULE = None
    if _ATO_MODULE is not None:
        logging.getLogger("run_kavach").info("Stopping ATO Protection module...")
        _ATO_MODULE.stop()
        _ATO_MODULE = None


def main() -> None:
    global _ATO_MODULE, _RATRIPAL_MODULE, _TOKEN_WATCH_STOP

    _configure_logging()
    logger = logging.getLogger("run_kavach")
    ensure_runtime_layout(ROOT)
    mode = get_mode(ROOT)
    logger.info("Batman mode: %s | logs: %s", mode, log_root(ROOT))
    logger.info(daily_ato_prompt_status_line(ROOT))
    warn = prod_hostname_guard(ROOT)
    if warn:
        logger.warning(warn)
    if _telegram_disabled():
        logger.warning(
            "KAVACH2_TELEGRAM_DISABLED=1 — Telegram polling OFF (web desk + ATO still run)"
        )

    _apply_mode_paths()
    global LOCK_PATH
    LOCK_PATH = bot_lock_path("kavach2", ROOT)
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
    warn_if_not_launched_via_bat("kavach2")
    bootstrap_exclusive_bot("kavach2", LOCK_PATH, logger, root=ROOT)
    atexit.register(_shutdown_ato)

    _health_state: dict = {"state": None}
    _runtime: dict = {"broker": None, "telegram_app": None}

    def _kavach_health() -> dict:
        st = _health_state.get("state")
        ok, detail = cache_consumer_status(path=default_cache_path())
        extra = {
            "deployment_confirmed": bool(st.get("deployment.confirmed")) if st else False,
            "ce_ato_active": bool(st.get("ato.ce_ato_active")) if st else False,
            "pe_ato_active": bool(st.get("ato.pe_ato_active")) if st else False,
            "nifty_cache_ready": ok,
            "nifty_cache_detail": detail,
            "broker_connected": _runtime["broker"] is not None,
        }
        try:
            from core.ato_readiness import compute_ato_readiness

            ready = compute_ato_readiness(state=st, check_services=True)
            extra["ato_armed"] = bool(ready.get("armed"))
            extra["ato_blocked_reasons"] = list(ready.get("hard_blocked_reasons") or [])
            extra["ato_summary"] = ready.get("summary_line")
        except Exception as exc:
            extra["ato_armed"] = False
            extra["ato_blocked_reasons"] = ["readiness_error"]
            extra["ato_summary"] = f"ATO readiness error: {exc}"
        return extra

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


    def _sync_broker_everywhere(broker) -> None:
        """Keep web desk + Telegram bot_data in sync after late token bootstrap."""
        _runtime["broker"] = broker
        try:
            from web.runtime import get_runtime

            rt = get_runtime()
            if rt is not None:
                rt.broker = broker
        except Exception as exc:
            logger.debug("web runtime broker sync skipped: %s", exc)
        app = _runtime.get("telegram_app")
        if app is not None:
            try:
                app.bot_data["broker"] = broker
            except Exception as exc:
                logger.debug("telegram broker sync skipped: %s", exc)

    def _bootstrap_from_token(token: str) -> None:
        global _ATO_MODULE
        if _runtime["broker"] is not None:
            return
        try:
            boot_broker = create_broker(client_code or "", token or "", ROOT)
        except Exception as exc:
            logger.error("KAVACH broker bootstrap failed: %s", exc)
            return
        _sync_broker_everywhere(boot_broker)
        apply_runtime_mode_provider(boot_broker, state)
        logger.info("KAVACH 2.0 broker bootstrapped from token file")
        if _ATO_MODULE is None:
            _ATO_MODULE = _start_ato_module(boot_broker, config, state, event_bus)
            if _RATRIPAL_MODULE is None:
                _RATRIPAL_MODULE = _start_ratripal_module(boot_broker, config, state, event_bus)

    broker = _connect_broker(client_code)
    _runtime["broker"] = broker
    if broker:
        if mode == "uat":
            logger.info("UAT ShadowBroker ready — /positions from screenshot book")
        else:
            logger.info("Broker connected — /positions and /register ready")
    else:
        logger.warning(
            "No broker at startup — will bootstrap when Zerodha access_token is available"
        )

    # Feeder writes NIFTY cache. IPC peeks only — no always-on collector.
    start_health_heartbeat(ROOT, "kavach2", extra_provider=_kavach_health)
    if _telegram_disabled():
        logger.info("ATO readiness Telegram notifier skipped (telegram disabled)")
    else:
        try:
            from core.ato_readiness_notify import start_ato_readiness_notifier
            start_ato_readiness_notifier()
        except Exception as exc:
            logger.warning("ATO readiness notifier not started: %s", exc)
    if state.get("deployment.confirmed", False):
        logger.info(
            "KAVACH 2.0 session restore: deployment.confirmed=True ce_ato=%s pe_ato=%s",
            state.get("ato.ce_ato_active", False),
            state.get("ato.pe_ato_active", False),
        )
    else:
        logger.info("KAVACH 2.0 session restore: no confirmed deployment — tap Register when ready")

    if broker:
        apply_runtime_mode_provider(broker, state)
        global _RATRIPAL_MODULE
        _ATO_MODULE = _start_ato_module(broker, config, state, event_bus)
        if _RATRIPAL_MODULE is None:
            _RATRIPAL_MODULE = _start_ratripal_module(broker, config, state, event_bus)

    if mode == "uat":
        _TOKEN_WATCH_STOP = start_token_watch(
            _runtime["broker"],
            client_code=client_code,
            token_path=access_token_path(ROOT),
            on_token_ready=_bootstrap_from_token,
        )
    else:
        from core.zerodha_credentials import start_zerodha_token_watch

        _TOKEN_WATCH_STOP = start_zerodha_token_watch(
            _runtime["broker"],
            root=ROOT,
            on_token_ready=_bootstrap_from_token,
        )

    try:
        from web.auth import ensure_web_secrets
        from web.runtime import WebRuntime, set_runtime
        from web.server import start_web_thread

        pw, secret = ensure_web_secrets()
        set_runtime(
            WebRuntime(
                root=ROOT,
                state=state,
                broker=_runtime["broker"],
                event_bus=event_bus,
                ato=_ATO_MODULE,
                client_code=client_code,
                web_password=pw,
                session_secret=secret,
            )
        )
        start_web_thread()
        logger.info("Kavach web desk thread started")
    except Exception as exc:
        logger.warning("Kavach web desk not started: %s", exc)

    if _telegram_disabled():
        logger.info(
            "Telegram halted — holding web desk + ATO only. "
            "Remove KAVACH2_TELEGRAM_DISABLED and restart batman-kavach2 to resume."
        )
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            logger.info("KAVACH 2.0 stopped by operator")
            return

    restart_policy = PollingRestartPolicy()
    session = 0
    failure_streak = 0
    while True:
        session += 1
        try:
            logger.info("Starting KAVACH 2.0 Telegram bot (session %s)...", session)
            app = build_application(
                broker=_runtime["broker"], state=state, event_bus=event_bus
            )
            _runtime["telegram_app"] = app
            app.run_polling(drop_pending_updates=True)
            failure_streak += 1
            restart_delay = restart_policy.delay_for_exception(None, failure_streak=failure_streak)
            logger.warning("KAVACH polling exited — restarting in %.1fs", restart_delay)
        except KeyboardInterrupt:
            logger.info("KAVACH 2.0 stopped by operator")
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
                "KAVACH 2.0 crashed: %s — restarting in %.1fs",
                exc,
                restart_delay,
                exc_info=True,
            )
        time.sleep(restart_delay)


if __name__ == "__main__":
    main()
