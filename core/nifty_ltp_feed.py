"""
NIFTY LTP feed — single collector, shared cache (Phase 1).

Architecture (locked):
  - DRISHTI is the only in-process feed orchestrator.
  - ``feed_mode=rest``: DRISHTI REST-poller writes ``data/nifty_ltp_cache.json``.
  - ``feed_mode=websocket``: in-process WebSocket feed inside DRISHTI (default).
  - KAVACH / ATO / all other bots **read cache only** — never call Dhan for NIFTY LTP.

One-shot WebSocket health checks remain in DRISHTI Telegram (diagnostic only).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time as _time_mod
import zoneinfo
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol

from core.bot_logging import bot_nifty_rest_ltp_log_dir, bot_nifty_websocket_ltp_log_dir
from core.exceptions import BrokerAuthError
from core.nifty_ltp import fetch_nifty_ltp_rest_with_retry, is_auth_error, is_rate_limit_error
from core.nifty_ltp_audit import append_rest_ltp_log

logger = logging.getLogger("batman.nifty_ltp_feed")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _ROOT / "data" / "nifty_ltp_feed_config.json"
# Legacy repo-relative path (tests / fallback only). Live reads/writes use
# ``default_cache_path()`` → ``batman_mode.nifty_ltp_cache_path`` (data_runtime shared).
_DEFAULT_CACHE_PATH = _ROOT / "data" / "nifty_ltp_cache.json"
_CACHE_WRITE_LOCK = threading.Lock()
_WINDOWS_REPLACE_RETRIES = 20
_WINDOWS_REPLACE_MAX_SLEEP_SECONDS = 0.25


def _resolved_cache_path(path: Path | None = None) -> Path:
    """Prefer runtime shared cache; fall back to legacy repo path if mode layout fails."""
    if path is not None:
        return path
    try:
        return default_cache_path()
    except Exception:
        return _DEFAULT_CACHE_PATH


def _is_retryable_windows_replace_error(exc: BaseException) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 5


def _atomic_replace(
    src: Path,
    dst: Path,
    *,
    retries: int = _WINDOWS_REPLACE_RETRIES,
    raise_on_failure: bool = True,
) -> bool:
    """Replace file atomically; retry on transient Windows file-lock races."""
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return True
        except (PermissionError, OSError) as exc:
            last_exc = exc
            if not _is_retryable_windows_replace_error(exc):
                if raise_on_failure:
                    raise
                return False
            sleep_s = min(0.025 * (attempt + 1), _WINDOWS_REPLACE_MAX_SLEEP_SECONDS)
            _time_mod.sleep(sleep_s)
    if last_exc is not None:
        if raise_on_failure:
            raise last_exc
        return False
    return False


def _default_rest_ltp_log_dir() -> Path:
    return bot_nifty_rest_ltp_log_dir(_ROOT)


def _default_websocket_ltp_log_dir() -> Path:
    return bot_nifty_websocket_ltp_log_dir(_ROOT)


POLL_INTERVAL_OPTIONS = (1, 2, 3, 5)
# UI Step 3 uses POLL_INTERVAL_OPTIONS; legacy values kept for existing configs.
STALE_PRICE_OPTIONS = (1, 2, 3, 5, 10, 15, 20, 25, 30)
USER_PING_WARNING_OPTIONS = (1, 2, 3, 5, 10, 15, 20, 30, 45, 60)
USER_PING_CRITICAL_OPTIONS = (1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120)
DEFAULT_USER_PING_WARNING_AGE_SECONDS = 15
DEFAULT_USER_PING_CRITICAL_AGE_SECONDS = 60
MIN_CRITICAL_ABOVE_WARNING_SECONDS = 0
FEED_MODE_REST = "rest"
FEED_MODE_WEBSOCKET = "websocket"
_LEGACY_EXTERNAL_WEBSOCKET = "external_websocket"
FEED_MODE_OPTIONS = (
    FEED_MODE_REST,
    FEED_MODE_WEBSOCKET,
)
DEFAULT_WEBSOCKET_STALE_CRITICAL_SECONDS = 5
DEFAULT_REST_STALE_CRITICAL_SECONDS = 10
DEFAULT_WS_STARTUP_GRACE_SECONDS = 30

_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 30)


class FeedAlertHooks(Protocol):
    async def on_fetch_failure(self, *, failures: int, threshold: int, error: str) -> None: ...

    async def on_auth_failure(self, *, error: str) -> None: ...

    async def on_fetch_recovered(self) -> None: ...

    async def on_feed_stale(self, *, age_seconds: float, threshold: float, error: str) -> None: ...

    async def on_feed_stale_cleared(self) -> None: ...

    async def on_stale_price(
        self, *, ltp: float, unchanged_seconds: float, threshold: int
    ) -> None: ...

    async def on_stale_price_cleared(self, *, ltp: float) -> None: ...


@dataclass
class NiftyLtpFeedConfig:
    """Operator-tuned feed settings (DRISHTI owns persistence)."""

    feed_mode: str = FEED_MODE_REST
    poll_interval_seconds: int = 2
    stale_price_alert_seconds: int = 10
    user_ping_warning_age_seconds: int = DEFAULT_USER_PING_WARNING_AGE_SECONDS
    user_ping_critical_age_seconds: int = DEFAULT_USER_PING_CRITICAL_AGE_SECONDS
    fetch_failure_jagran_threshold: int = 5
    log_enabled: bool = True
    rest_max_attempts: int = 3
    rest_retry_base_seconds: float = 1.0
    rest_retry_backoff_multiplier: float = 2.0
    rate_limit_cooldown_seconds: float = 30.0
    websocket_stale_critical_seconds: int = DEFAULT_WEBSOCKET_STALE_CRITICAL_SECONDS
    rest_stale_critical_seconds: int = DEFAULT_REST_STALE_CRITICAL_SECONDS
    websocket_startup_grace_seconds: int = DEFAULT_WS_STARTUP_GRACE_SECONDS

    def is_websocket_mode(self) -> bool:
        return self.feed_mode == FEED_MODE_WEBSOCKET

    def uses_websocket_transport(self) -> bool:
        return self.is_websocket_mode()

    def consumer_max_age_seconds(self) -> float:
        """Max cache age before KAVACH/ATO treat LTP as stale (by transport)."""
        if self.uses_websocket_transport():
            return float(self.websocket_stale_critical_seconds)
        return float(self.rest_stale_critical_seconds)

    def cache_max_age_seconds(self) -> float:
        """Alias for feed watch / consumer freshness (mode-aware)."""
        return self.consumer_max_age_seconds()

    def min_user_ping_warning_age_seconds(self) -> int:
        """Warning threshold cannot be below background feed freshness."""
        return int(self.consumer_max_age_seconds())

    def effective_user_ping_warning_age_seconds(self) -> float:
        return float(
            max(self.user_ping_warning_age_seconds, self.min_user_ping_warning_age_seconds())
        )

    def effective_user_ping_critical_age_seconds(self) -> float:
        warn = int(self.effective_user_ping_warning_age_seconds())
        floor = warn + MIN_CRITICAL_ABOVE_WARNING_SECONDS
        return float(max(self.user_ping_critical_age_seconds, floor))

    def is_valid_user_ping_thresholds(self) -> bool:
        try:
            self._validate_user_ping_thresholds()
            return True
        except ValueError:
            return False

    def _validate_user_ping_thresholds(self) -> None:
        if self.user_ping_warning_age_seconds not in USER_PING_WARNING_OPTIONS:
            raise ValueError(
                f"user_ping_warning_age_seconds must be one of {USER_PING_WARNING_OPTIONS}"
            )
        if self.user_ping_critical_age_seconds not in USER_PING_CRITICAL_OPTIONS:
            raise ValueError(
                f"user_ping_critical_age_seconds must be one of {USER_PING_CRITICAL_OPTIONS}"
            )
        feed_min = self.min_user_ping_warning_age_seconds()
        # Stored warning may be below feed freshness; effective_* floors apply at runtime.
        _ = feed_min
        if self.websocket_stale_critical_seconds < 1:
            raise ValueError("websocket_stale_critical_seconds must be >= 1")
        if self.rest_stale_critical_seconds < 1:
            raise ValueError("rest_stale_critical_seconds must be >= 1")
        if self.websocket_startup_grace_seconds < 1:
            raise ValueError("websocket_startup_grace_seconds must be >= 1")
        min_crit = self.user_ping_warning_age_seconds + MIN_CRITICAL_ABOVE_WARNING_SECONDS
        if self.user_ping_critical_age_seconds < min_crit:
            raise ValueError(
                f"user_ping_critical_age_seconds must be >= {min_crit}s "
                f"(warning {self.user_ping_warning_age_seconds}s)"
            )

    def is_rest_mode(self) -> bool:
        return self.feed_mode == FEED_MODE_REST

    def __post_init__(self) -> None:
        if self.feed_mode not in FEED_MODE_OPTIONS:
            raise ValueError(f"feed_mode must be one of {FEED_MODE_OPTIONS}")
        if self.poll_interval_seconds not in POLL_INTERVAL_OPTIONS:
            raise ValueError(f"poll_interval_seconds must be one of {POLL_INTERVAL_OPTIONS}")
        if self.stale_price_alert_seconds not in STALE_PRICE_OPTIONS:
            raise ValueError(f"stale_price_alert_seconds must be one of {STALE_PRICE_OPTIONS}")
        self._validate_user_ping_thresholds()
        if self.fetch_failure_jagran_threshold < 1:
            raise ValueError("fetch_failure_jagran_threshold must be >= 1")
        if self.rest_max_attempts < 1:
            raise ValueError("rest_max_attempts must be >= 1")
        if self.rest_retry_base_seconds <= 0:
            raise ValueError("rest_retry_base_seconds must be > 0")
        if self.rest_retry_backoff_multiplier < 1.0:
            raise ValueError("rest_retry_backoff_multiplier must be >= 1")
        if self.rate_limit_cooldown_seconds < 0:
            raise ValueError("rate_limit_cooldown_seconds must be >= 0")


@dataclass
class NiftyLtpCacheSnapshot:
    ltp: float
    updated_at: str
    last_changed_at: str
    source: str = "dhan_rest"
    feed_healthy: bool = True
    poll_interval_seconds: int = 2
    consecutive_failures: int = 0
    unchanged_seconds: float = 0.0
    collector: str = "drishti"
    collector_pid: int | None = None
    # Present when source=uat_replay — market clock of the emitted tick (ISO IST).
    replay_market_time: str | None = None

    def age_seconds(self, now: datetime | None = None) -> float:
        now = now or datetime.now(_IST)
        try:
            updated = datetime.fromisoformat(self.updated_at)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=_IST)
            return max(0.0, (now - updated.astimezone(_IST)).total_seconds())
        except (TypeError, ValueError):
            return float("inf")

    def is_fresh(self, max_age_seconds: float, now: datetime | None = None) -> bool:
        return self.feed_healthy and self.ltp > 0 and self.age_seconds(now) <= max_age_seconds

    def ready_for_consumers(
        self, max_age_seconds: float | None = None, now: datetime | None = None
    ) -> bool:
        """True when KAVACH/ATO may trust this cache without calling DRISHTI."""
        if max_age_seconds is not None:
            age_limit = float(max_age_seconds)
        else:
            cfg = load_feed_config()
            age_limit = (
                cfg.consumer_max_age_seconds()
                if cfg
                else float(max(self.poll_interval_seconds * 3, 6))
            )
        return self.is_fresh(age_limit, now)


def default_config_path() -> Path:
    return _DEFAULT_CONFIG_PATH


def default_cache_path() -> Path:
    from core.batman_mode import nifty_ltp_cache_path

    return nifty_ltp_cache_path()


def feed_freshness_floor_seconds(
    poll_interval_seconds: int,
    *,
    feed_mode: str = FEED_MODE_REST,
) -> int:
    """Minimum cache age before user-ping warning thresholds apply."""
    if feed_mode == FEED_MODE_WEBSOCKET:
        return DEFAULT_WEBSOCKET_STALE_CRITICAL_SECONDS
    return max(int(poll_interval_seconds) * 3, 6)


def allowed_user_ping_warning_options(
    poll_interval_seconds: int,
    *,
    feed_mode: str = FEED_MODE_REST,
) -> tuple[int, ...]:
    """Warning ages valid for a given poll interval (must exceed feed freshness)."""
    floor = feed_freshness_floor_seconds(poll_interval_seconds, feed_mode=feed_mode)
    opts = [v for v in USER_PING_WARNING_OPTIONS if v >= floor]
    return tuple(opts if opts else (max(USER_PING_WARNING_OPTIONS),))


def allowed_user_ping_critical_options(warning_seconds: int) -> tuple[int, ...]:
    """Critical ages valid for a chosen warning threshold."""
    floor = int(warning_seconds) + MIN_CRITICAL_ABOVE_WARNING_SECONDS
    opts = [v for v in USER_PING_CRITICAL_OPTIONS if v >= floor]
    return tuple(opts if opts else (max(USER_PING_CRITICAL_OPTIONS),))


def load_feed_config(path: Path | None = None) -> NiftyLtpFeedConfig | None:
    cfg_path = path or _DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return None
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return None
        mode = str(raw.get("feed_mode", FEED_MODE_REST))
        if mode == _LEGACY_EXTERNAL_WEBSOCKET:
            logger.info(
                "Migrating legacy feed_mode %s → %s in %s",
                _LEGACY_EXTERNAL_WEBSOCKET,
                FEED_MODE_WEBSOCKET,
                cfg_path,
            )
            mode = FEED_MODE_WEBSOCKET
        elif mode not in FEED_MODE_OPTIONS:
            mode = FEED_MODE_REST
        return NiftyLtpFeedConfig(
            feed_mode=mode,
            poll_interval_seconds=int(raw.get("poll_interval_seconds", 2)),
            stale_price_alert_seconds=int(raw.get("stale_price_alert_seconds", 10)),
            user_ping_warning_age_seconds=int(
                raw.get("user_ping_warning_age_seconds", DEFAULT_USER_PING_WARNING_AGE_SECONDS)
            ),
            user_ping_critical_age_seconds=int(
                raw.get("user_ping_critical_age_seconds", DEFAULT_USER_PING_CRITICAL_AGE_SECONDS)
            ),
            fetch_failure_jagran_threshold=int(raw.get("fetch_failure_jagran_threshold", 5)),
            log_enabled=bool(raw.get("log_enabled", True)),
            rest_max_attempts=int(raw.get("rest_max_attempts", 3)),
            rest_retry_base_seconds=float(raw.get("rest_retry_base_seconds", 1.0)),
            rest_retry_backoff_multiplier=float(raw.get("rest_retry_backoff_multiplier", 2.0)),
            rate_limit_cooldown_seconds=float(raw.get("rate_limit_cooldown_seconds", 30.0)),
            websocket_stale_critical_seconds=int(
                raw.get(
                    "websocket_stale_critical_seconds", DEFAULT_WEBSOCKET_STALE_CRITICAL_SECONDS
                )
            ),
            rest_stale_critical_seconds=int(
                raw.get("rest_stale_critical_seconds", DEFAULT_REST_STALE_CRITICAL_SECONDS)
            ),
            websocket_startup_grace_seconds=int(
                raw.get("websocket_startup_grace_seconds", DEFAULT_WS_STARTUP_GRACE_SECONDS)
            ),
        )
    except Exception as exc:
        logger.warning("Could not load NIFTY feed config from %s: %s", cfg_path, exc)
        return None


def save_feed_config(config: NiftyLtpFeedConfig, path: Path | None = None) -> None:
    cfg_path = path or _DEFAULT_CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    payload["configured_at"] = datetime.now(_IST).isoformat()
    with _CACHE_WRITE_LOCK:
        tmp = cfg_path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            _atomic_replace(tmp, cfg_path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


def read_nifty_ltp_cache(path: Path | None = None) -> NiftyLtpCacheSnapshot | None:
    """Read shared cache; retry briefly when DRISHTI replaces the file (Windows dev)."""
    cache_path = _resolved_cache_path(path)
    if not cache_path.exists():
        return None
    last_exc: BaseException | None = None
    for attempt in range(6):
        try:
            with open(cache_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict) or raw.get("ltp") is None:
                return None
            return NiftyLtpCacheSnapshot(
                ltp=float(raw["ltp"]),
                updated_at=str(raw.get("updated_at", "")),
                last_changed_at=str(raw.get("last_changed_at", raw.get("updated_at", ""))),
                source=str(raw.get("source", "dhan_rest")),
                feed_healthy=bool(raw.get("feed_healthy", True)),
                poll_interval_seconds=int(raw.get("poll_interval_seconds", 2)),
                consecutive_failures=int(raw.get("consecutive_failures", 0)),
                unchanged_seconds=float(raw.get("unchanged_seconds", 0.0)),
                collector=str(raw.get("collector", "drishti")),
                collector_pid=int(raw["collector_pid"]) if raw.get("collector_pid") else None,
                replay_market_time=(
                    str(raw["replay_market_time"])
                    if raw.get("replay_market_time")
                    else None
                ),
            )
        except (PermissionError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt < 5:
                _time_mod.sleep(0.05 * (attempt + 1))
                continue
        except Exception as exc:
            logger.debug("NIFTY cache read failed: %s", exc)
            return None
    if last_exc is not None:
        logger.debug("NIFTY cache read failed after retries: %s", last_exc)
    return None


def get_cached_nifty_ltp(
    *,
    max_age_seconds: float,
    path: Path | None = None,
) -> float | None:
    snap = read_nifty_ltp_cache(path)
    if snap is None or not snap.is_fresh(max_age_seconds):
        return None
    return snap.ltp


def consumer_max_age_for_trading(
    *,
    config_override: float | None = None,
) -> float:
    """Mode-aware consumer freshness limit for KAVACH/ATO."""
    if config_override is not None:
        return float(config_override)
    cfg = load_feed_config()
    if cfg is not None:
        return cfg.consumer_max_age_seconds()
    return 6.0


def resolve_nifty_ltp_from_cache(
    *,
    max_age_seconds: float | None = None,
    path: Path | None = None,
) -> float:
    """Return fresh NIFTY LTP from DRISHTI cache — sole path for trading bots."""
    from core.exceptions import BrokerConnectionError

    age = consumer_max_age_for_trading(config_override=max_age_seconds)
    cached = get_cached_nifty_ltp(max_age_seconds=age, path=path)
    if cached is None:
        raise BrokerConnectionError(
            "NIFTY LTP cache stale or missing. Ensure DRISHTI feed is running "
            "(REST or WebSocket mode)."
        )
    return cached


def cache_consumer_status(
    *,
    path: Path | None = None,
    max_age_seconds: float | None = None,
) -> tuple[bool, str]:
    """Return (ready, detail) for KAVACH/ATO/startup gates — read file only."""
    snap = read_nifty_ltp_cache(path)
    if snap is None:
        return False, "NIFTY LTP cache missing"
    age = snap.age_seconds()
    limit = float(max_age_seconds or consumer_max_age_for_trading())
    if snap.ready_for_consumers(limit):
        return (
            True,
            f"LTP={snap.ltp:,.2f} age={age:.0f}s collector={snap.collector}",
        )
    return (
        False,
        f"cache not ready age={age:.0f}s limit={limit:.0f}s "
        f"healthy={snap.feed_healthy} failures={snap.consecutive_failures}",
    )


def write_nifty_ltp_cache(snapshot: NiftyLtpCacheSnapshot, path: Path | None = None) -> bool:
    cache_path = _resolved_cache_path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(_IST)
    payload = asdict(snapshot)
    if payload.get("collector_pid") is None:
        payload["collector_pid"] = os.getpid()
    payload["cache_age_seconds"] = round(snapshot.age_seconds(now), 2)
    age_limit = consumer_max_age_for_trading()
    payload["ready_for_consumers"] = snapshot.ready_for_consumers(age_limit, now)
    with _CACHE_WRITE_LOCK:
        tmp = cache_path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            replaced = _atomic_replace(tmp, cache_path, raise_on_failure=False)
            if not replaced:
                logger.warning(
                    "NIFTY cache replace deferred after repeated Windows file-lock retries: %s",
                    cache_path,
                )
            return replaced
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    return False


def seed_nifty_ltp_cache(
    ltp: float,
    *,
    source: str = "dhan_rest",
    feed_healthy: bool = True,
    poll_interval_seconds: int = 2,
    path: Path | None = None,
) -> NiftyLtpCacheSnapshot:
    """Write a fresh LTP snapshot (token save, on-demand Telegram fetch)."""
    now = datetime.now(_IST)
    snap = NiftyLtpCacheSnapshot(
        ltp=float(ltp),
        updated_at=now.isoformat(),
        last_changed_at=now.isoformat(),
        source=source,
        feed_healthy=feed_healthy,
        poll_interval_seconds=poll_interval_seconds,
        consecutive_failures=0,
        unchanged_seconds=0.0,
    )
    write_nifty_ltp_cache(snap, path)
    return snap


def is_nse_market_session(
    now: datetime | None = None,
    *,
    trading_day_check: Callable[[date], bool] | None = None,
) -> bool:
    """True during NSE cash session window (09:15–15:30 IST) on a trading day."""
    now = now or datetime.now(_IST)
    if trading_day_check is not None and not trading_day_check(now.date()):
        return False
    t = now.time()
    return _MARKET_OPEN <= t <= _MARKET_CLOSE


def market_open_datetime(
    now: datetime | None = None,
    *,
    trading_day_check: Callable[[date], bool] | None = None,
) -> datetime | None:
    """Today's 09:15 IST when session is active; None off-hours or non-trading day."""
    now = now or datetime.now(_IST)
    if not is_nse_market_session(now, trading_day_check=trading_day_check):
        return None
    return datetime.combine(now.date(), _MARKET_OPEN, tzinfo=_IST)


def seconds_since_market_open(
    now: datetime | None = None,
    *,
    trading_day_check: Callable[[date], bool] | None = None,
) -> float | None:
    """Seconds elapsed since 09:15 IST today, or None if not in session."""
    now = now or datetime.now(_IST)
    opened = market_open_datetime(now, trading_day_check=trading_day_check)
    if opened is None:
        return None
    return max(0.0, (now - opened).total_seconds())


def is_within_feed_startup_grace(
    now: datetime | None = None,
    *,
    grace_seconds: int = DEFAULT_WS_STARTUP_GRACE_SECONDS,
    trading_day_check: Callable[[date], bool] | None = None,
) -> bool:
    """True during the first *grace_seconds* after 09:15 on a trading day."""
    elapsed = seconds_since_market_open(now, trading_day_check=trading_day_check)
    if elapsed is None:
        return False
    return elapsed < float(grace_seconds)


def compute_unchanged_seconds(
    *,
    previous_ltp: float | None,
    new_ltp: float,
    last_changed_at: datetime | None,
    now: datetime,
) -> tuple[float, datetime]:
    """Return (unchanged_seconds, updated_last_changed_at)."""
    if previous_ltp is None or new_ltp != previous_ltp:
        return 0.0, now
    if last_changed_at is None:
        return 0.0, now
    return max(0.0, (now - last_changed_at).total_seconds()), last_changed_at


def should_alert_stale_price(
    unchanged_seconds: float,
    threshold_seconds: int,
    *,
    in_market_session: bool,
) -> bool:
    return in_market_session and unchanged_seconds >= float(threshold_seconds)


@dataclass
class _FeedRuntime:
    last_ltp: float | None = None
    last_changed_at: datetime | None = None
    last_update_at: datetime | None = None
    transport_started_at: datetime | None = None
    consecutive_failures: int = 0
    fetch_jagran_sent: bool = False
    feed_stale_jagran_sent: bool = False
    stale_jagran_sent: bool = False
    rate_limit_until: datetime | None = None


def is_within_transport_grace(
    runtime: _FeedRuntime,
    *,
    grace_seconds: int,
    now: datetime | None = None,
) -> bool:
    """True during grace after WS connect / REST service start (mid-session reconnect)."""
    started = runtime.transport_started_at
    if started is None:
        return False
    when = now or datetime.now(_IST)
    return (when - started).total_seconds() < float(grace_seconds)


def mark_transport_started(runtime: _FeedRuntime, when: datetime | None = None) -> None:
    runtime.transport_started_at = when or datetime.now(_IST)
    runtime.feed_stale_jagran_sent = False


async def run_feed_stale_watchdog(
    *,
    config: NiftyLtpFeedConfig,
    runtime: _FeedRuntime,
    hooks: FeedAlertHooks | None,
    is_running: Callable[[], bool],
    trading_day_check: Callable[[date], bool] | None = None,
    check_interval_seconds: float = 1.0,
) -> None:
    """Alert when no tick/poll refreshed ``updated_at`` within mode threshold."""
    threshold = config.consumer_max_age_seconds()
    while is_running():
        try:
            await asyncio.sleep(check_interval_seconds)
            now = datetime.now(_IST)
            if not is_nse_market_session(now, trading_day_check=trading_day_check):
                if runtime.feed_stale_jagran_sent:
                    runtime.feed_stale_jagran_sent = False
                    if hooks is not None:
                        await hooks.on_feed_stale_cleared()
                continue
            last = runtime.last_update_at
            if runtime.rate_limit_until is not None and now < runtime.rate_limit_until:
                continue
            if last is None:
                grace_s = int(
                    getattr(
                        config, "websocket_startup_grace_seconds", DEFAULT_WS_STARTUP_GRACE_SECONDS
                    )
                )
                if config.uses_websocket_transport() and (
                    is_within_feed_startup_grace(
                        now,
                        grace_seconds=grace_s,
                        trading_day_check=trading_day_check,
                    )
                    or is_within_transport_grace(runtime, grace_seconds=grace_s, now=now)
                ):
                    continue
                if hooks is not None and not runtime.feed_stale_jagran_sent:
                    runtime.feed_stale_jagran_sent = True
                    error = f"No NIFTY feed tick received since 09:15 " f"(mode={config.feed_mode})"
                    await hooks.on_feed_stale(
                        age_seconds=float(grace_s + 1),
                        threshold=float(config.consumer_max_age_seconds()),
                        error=error,
                    )
                continue
            age = max(0.0, (now - last).total_seconds())
            if runtime.rate_limit_until is not None and now < runtime.rate_limit_until:
                continue
            if age > threshold:
                if hooks is not None and not runtime.feed_stale_jagran_sent:
                    runtime.feed_stale_jagran_sent = True
                    error = (
                        f"No NIFTY feed refresh for {age:.1f}s "
                        f"(limit {threshold:.0f}s, mode={config.feed_mode})"
                    )
                    await hooks.on_feed_stale(
                        age_seconds=age,
                        threshold=threshold,
                        error=error,
                    )
            elif runtime.feed_stale_jagran_sent:
                runtime.feed_stale_jagran_sent = False
                if hooks is not None:
                    await hooks.on_feed_stale_cleared()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("NIFTY feed stale watchdog error: %s", exc)


def _append_ltp_log(
    log_dir: Path,
    now: datetime,
    ltp: float,
    source: str,
    event: str = "ok",
) -> None:
    """Append one NIFTY audit line under today's DRISHTI ``logs/nifty_ltp/`` folder."""
    append_nifty_ltp_audit_log(log_dir, now, ltp, source, event=event)


def append_nifty_ltp_audit_log(
    log_dir: Path,
    now: datetime,
    ltp: float,
    source: str,
    *,
    event: str = "ok",
) -> Path:
    """Write ``timestamp,ltp,source,event`` to the daily DRISHTI NIFTY audit file."""
    log_dir.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y%m%d")
    log_path = log_dir / f"nifty_ltp_{day}.log"
    line = f"{now.strftime('%Y-%m-%d %H:%M:%S')} IST," f"{ltp:.2f}," f"{source}," f"{event}\n"
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(line)
    return log_path


def is_nifty_feed_task_running(service: object | None) -> bool:
    """True when a feed asyncio task is active."""
    if service is None:
        return False
    running = getattr(service, "_running", False)
    task = getattr(service, "_task", None)
    return bool(running and task is not None and not task.done())


class NiftyLtpFeedService:
    """Background REST poller — start via ``asyncio.create_task(service.run())``."""

    def __init__(
        self,
        *,
        client_code: str,
        token_getter: Callable[[], str | None],
        config: NiftyLtpFeedConfig,
        hooks: FeedAlertHooks | None = None,
        cache_path: Path | None = None,
        log_dir: Path | None = None,
        trading_day_check: Callable[[date], bool] | None = None,
    ) -> None:
        self.client_code = client_code
        self.token_getter = token_getter
        self.config = config
        self.hooks = hooks
        self.cache_path = cache_path or default_cache_path()
        self.log_dir = log_dir or _default_rest_ltp_log_dir()
        self.trading_day_check = trading_day_check
        self._runtime = _FeedRuntime()
        self._running = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        if self._task and not self._task.done():
            self._task.cancel()
        self._running = True
        self._task = asyncio.create_task(self.run(), name="nifty_ltp_feed")
        return self._task

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def run(self) -> None:
        logger.info(
            "NIFTY REST feed started — poll=%ss consumer_stale=%ss",
            self.config.poll_interval_seconds,
            self.config.rest_stale_critical_seconds,
        )
        mark_transport_started(self._runtime)
        watchdog = asyncio.create_task(
            run_feed_stale_watchdog(
                config=self.config,
                runtime=self._runtime,
                hooks=self.hooks,
                is_running=lambda: self._running,
                trading_day_check=self.trading_day_check,
            ),
            name="nifty_rest_stale_watchdog",
        )
        try:
            while self._running:
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("NIFTY feed tick error: %s", exc)
                sleep_s = float(self.config.poll_interval_seconds)
                rt = self._runtime
                if rt.rate_limit_until is not None:
                    now = datetime.now(_IST)
                    if now < rt.rate_limit_until:
                        cooldown = (rt.rate_limit_until - now).total_seconds()
                        sleep_s = max(sleep_s, cooldown)
                await asyncio.sleep(sleep_s)
        finally:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog

    async def _tick(self) -> None:
        now = datetime.now(_IST)
        in_session = is_nse_market_session(now, trading_day_check=self.trading_day_check)

        if not in_session:
            await self._handle_off_session(now)
            return

        rt = self._runtime
        if rt.rate_limit_until is not None and now < rt.rate_limit_until:
            logger.debug(
                "NIFTY feed rate-limit cooldown until %s",
                rt.rate_limit_until.strftime("%H:%M:%S"),
            )
            return

        token = self.token_getter()
        if not token or not self.client_code:
            return

        try:
            ltp = await asyncio.to_thread(
                fetch_nifty_ltp_rest_with_retry,
                self.client_code,
                token,
                max_attempts=self.config.rest_max_attempts,
                base_delay_seconds=self.config.rest_retry_base_seconds,
                backoff_multiplier=self.config.rest_retry_backoff_multiplier,
                rate_limit_extra_seconds=self.config.rate_limit_cooldown_seconds / 3.0,
            )
            rt.rate_limit_until = None
        except BrokerAuthError as exc:
            await self._handle_auth_failure(str(exc), now)
            return
        except Exception as exc:
            error = str(exc)
            if is_rate_limit_error(error):
                await self._handle_rate_limit(error, now)
                return
            await self._handle_fetch_failure(error, now)
            return

        await self._handle_fetch_success(ltp, now, in_session)

    async def _handle_off_session(self, now: datetime) -> None:
        """Mark shared cache stale when poller is idle outside market hours."""
        snap = read_nifty_ltp_cache(self.cache_path)
        if snap is None:
            return
        max_age = self.config.cache_max_age_seconds()
        if snap.feed_healthy and snap.age_seconds(now) > max_age:
            write_nifty_ltp_cache(
                NiftyLtpCacheSnapshot(
                    ltp=float(snap.ltp),
                    updated_at=snap.updated_at,
                    last_changed_at=snap.last_changed_at,
                    source=snap.source,
                    feed_healthy=False,
                    poll_interval_seconds=self.config.poll_interval_seconds,
                    consecutive_failures=snap.consecutive_failures,
                    unchanged_seconds=snap.unchanged_seconds,
                ),
                self.cache_path,
            )
            logger.debug(
                "NIFTY cache marked unhealthy (off-session, age=%.0fs)",
                snap.age_seconds(now),
            )

    async def _handle_rate_limit(self, error: str, now: datetime) -> None:
        rt = self._runtime
        cooldown = self.config.rate_limit_cooldown_seconds
        rt.rate_limit_until = now + timedelta(seconds=cooldown)
        logger.warning(
            "NIFTY REST rate limited — cooldown %.0fs (failures=%s, not escalated): %s",
            cooldown,
            rt.consecutive_failures,
            error[:120],
        )
        if rt.last_ltp is not None and rt.last_changed_at is not None:
            snap = NiftyLtpCacheSnapshot(
                ltp=float(rt.last_ltp),
                updated_at=now.isoformat(),
                last_changed_at=rt.last_changed_at.isoformat(),
                source="dhan_rest",
                feed_healthy=True,
                poll_interval_seconds=self.config.poll_interval_seconds,
                consecutive_failures=rt.consecutive_failures,
            )
            write_nifty_ltp_cache(snap, self.cache_path)
        if self.config.log_enabled:
            await asyncio.to_thread(
                append_rest_ltp_log,
                self.log_dir,
                now,
                float(rt.last_ltp or 0.0),
                event="rate_limit",
            )

    async def _handle_auth_failure(self, error: str, now: datetime) -> None:
        """Invalid JWT — do not increment failure streak or trigger transport failover."""
        rt = self._runtime
        logger.error("NIFTY REST auth failure (no retry): %s", error[:160])
        snap = NiftyLtpCacheSnapshot(
            ltp=float(rt.last_ltp or 0.0),
            updated_at=now.isoformat(),
            last_changed_at=(rt.last_changed_at or now).isoformat(),
            source="dhan_rest",
            feed_healthy=False,
            poll_interval_seconds=self.config.poll_interval_seconds,
            consecutive_failures=rt.consecutive_failures,
        )
        write_nifty_ltp_cache(snap, self.cache_path)
        if self.config.log_enabled:
            await asyncio.to_thread(
                append_rest_ltp_log,
                self.log_dir,
                now,
                snap.ltp,
                event="auth_error",
            )
        if self.hooks is not None and not rt.fetch_jagran_sent:
            rt.fetch_jagran_sent = True
            await self.hooks.on_auth_failure(error=error)

    async def _handle_fetch_failure(self, error: str, now: datetime) -> None:
        if is_auth_error(error):
            await self._handle_auth_failure(error, now)
            return
        rt = self._runtime
        rt.consecutive_failures += 1
        snap = NiftyLtpCacheSnapshot(
            ltp=float(rt.last_ltp or 0.0),
            updated_at=now.isoformat(),
            last_changed_at=(rt.last_changed_at or now).isoformat(),
            source="dhan_rest",
            feed_healthy=False,
            poll_interval_seconds=self.config.poll_interval_seconds,
            consecutive_failures=rt.consecutive_failures,
        )
        write_nifty_ltp_cache(snap, self.cache_path)
        if self.config.log_enabled:
            await asyncio.to_thread(
                append_rest_ltp_log,
                self.log_dir,
                now,
                snap.ltp,
                event=f"error:{error[:60]}",
            )

        threshold = self.config.fetch_failure_jagran_threshold
        if (
            self.hooks is not None
            and rt.consecutive_failures >= threshold
            and not rt.fetch_jagran_sent
        ):
            rt.fetch_jagran_sent = True
            await self.hooks.on_fetch_failure(
                failures=rt.consecutive_failures,
                threshold=threshold,
                error=error,
            )
        logger.warning(
            "NIFTY REST fetch failed (%s/%s): %s",
            rt.consecutive_failures,
            threshold,
            error,
        )

    async def _handle_fetch_success(self, ltp: float, now: datetime, in_session: bool) -> None:
        rt = self._runtime
        if rt.consecutive_failures > 0 or rt.fetch_jagran_sent:
            if self.hooks is not None and rt.fetch_jagran_sent:
                await self.hooks.on_fetch_recovered()
            rt.fetch_jagran_sent = False
        rt.consecutive_failures = 0

        unchanged_seconds, rt.last_changed_at = compute_unchanged_seconds(
            previous_ltp=rt.last_ltp,
            new_ltp=ltp,
            last_changed_at=rt.last_changed_at,
            now=now,
        )
        if rt.last_ltp is None or ltp != rt.last_ltp:
            rt.last_changed_at = now
            unchanged_seconds = 0.0
        rt.last_ltp = ltp
        rt.last_update_at = now

        snap = NiftyLtpCacheSnapshot(
            ltp=ltp,
            updated_at=now.isoformat(),
            last_changed_at=rt.last_changed_at.isoformat(),
            source="dhan_rest",
            feed_healthy=True,
            poll_interval_seconds=self.config.poll_interval_seconds,
            consecutive_failures=0,
            unchanged_seconds=unchanged_seconds,
        )
        write_nifty_ltp_cache(snap, self.cache_path)

        if self.config.log_enabled:
            await asyncio.to_thread(append_rest_ltp_log, self.log_dir, now, ltp)
            try:
                from core.ato_nifty_tick_csv import record_nifty_tick

                record_nifty_tick(now, float(ltp), source="nifty_rest")
            except Exception:
                pass

        if should_alert_stale_price(
            unchanged_seconds,
            self.config.stale_price_alert_seconds,
            in_market_session=in_session,
        ):
            if self.hooks is not None and not rt.stale_jagran_sent:
                rt.stale_jagran_sent = True
                await self.hooks.on_stale_price(
                    ltp=ltp,
                    unchanged_seconds=unchanged_seconds,
                    threshold=self.config.stale_price_alert_seconds,
                )
        elif rt.stale_jagran_sent and unchanged_seconds == 0.0:
            rt.stale_jagran_sent = False
            if self.hooks is not None:
                await self.hooks.on_stale_price_cleared(ltp=ltp)

        logger.debug(
            "NIFTY LTP=%.2f unchanged=%.1fs",
            ltp,
            unchanged_seconds,
        )


class _NoOpHooks:
    async def on_fetch_failure(self, *, failures: int, threshold: int, error: str) -> None:
        return None

    async def on_auth_failure(self, *, error: str) -> None:
        return None

    async def on_fetch_recovered(self) -> None:
        return None

    async def on_feed_stale(self, *, age_seconds: float, threshold: float, error: str) -> None:
        return None

    async def on_feed_stale_cleared(self) -> None:
        return None

    async def on_stale_price(self, *, ltp: float, unchanged_seconds: float, threshold: int) -> None:
        return None

    async def on_stale_price_cleared(self, *, ltp: float) -> None:
        return None
