"""Market data provider strategy for DRISHTI (LIVE vs UAT Replay).

Downstream robots (KAVACH / Coverage / ATO) keep reading the shared NIFTY cache
via ``resolve_nifty_ltp_from_cache`` / ``get_cached_nifty_ltp`` — they never choose
a provider. DRISHTI alone selects which writer feeds that cache.

Architecture::

    MarketDataProvider
    ├── LiveMarketProvider   (production WS/REST → shared cache)
    └── ReplayMarketProvider (UAT tick replay → same shared cache)

Consumer API remains ``get_nifty_ltp()`` / ``resolve_nifty_ltp_from_cache()``.
"""

from __future__ import annotations

import logging
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Protocol, runtime_checkable

from core.nifty_ltp_feed import (
    NiftyLtpCacheSnapshot,
    get_cached_nifty_ltp,
    is_nse_market_session,
    read_nifty_ltp_cache,
    resolve_nifty_ltp_from_cache,
)
from core.nifty_ltp_uat_replay import (
    UAT_LOG_TAG,
    NiftyLtpUatReplayConfig,
    is_drishti_uat_replay_window,
)

logger = logging.getLogger("batman.market_data_provider")

LIVE_LOG_TAG = "[DRISHTI LIVE]"
_IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# Spec production clock for mode selection (IST). Live collectors still emit
# only during NSE cash session 09:15–15:30.
_PROD_MODE_OPEN = time(9, 0)
_PROD_MODE_CLOSE = time(15, 30)


class MarketDataMode(str, Enum):
    LIVE = "live"
    UAT_REPLAY = "uat_replay"


@runtime_checkable
class MarketDataProvider(Protocol):
    """Abstraction used by DRISHTI orchestration — not by Coverage/ATO."""

    @property
    def mode(self) -> MarketDataMode: ...

    def get_nifty_ltp(self, *, max_age_seconds: float | None = None) -> float:
        """Same contract downstream already uses (cache-backed)."""
        ...

    def read_snapshot(self) -> NiftyLtpCacheSnapshot | None: ...


@dataclass(frozen=True)
class LiveMarketProvider:
    """Production path — LTP from live WS/REST writers into the shared cache."""

    @property
    def mode(self) -> MarketDataMode:
        return MarketDataMode.LIVE

    def get_nifty_ltp(self, *, max_age_seconds: float | None = None) -> float:
        return resolve_nifty_ltp_from_cache(max_age_seconds=max_age_seconds)

    def read_snapshot(self) -> NiftyLtpCacheSnapshot | None:
        return read_nifty_ltp_cache()


@dataclass(frozen=True)
class ReplayMarketProvider:
    """UAT path — LTP from replay writer into the same shared cache."""

    @property
    def mode(self) -> MarketDataMode:
        return MarketDataMode.UAT_REPLAY

    def get_nifty_ltp(self, *, max_age_seconds: float | None = None) -> float:
        return resolve_nifty_ltp_from_cache(max_age_seconds=max_age_seconds)

    def read_snapshot(self) -> NiftyLtpCacheSnapshot | None:
        return read_nifty_ltp_cache()


def is_production_clock_hours(now: datetime | None = None) -> bool:
    """True for 09:00–15:30 IST (spec production clock; not NSE emit window)."""
    when = now or datetime.now(_IST)
    if when.tzinfo is None:
        when = when.replace(tzinfo=_IST)
    else:
        when = when.astimezone(_IST)
    t = when.time()
    return _PROD_MODE_OPEN <= t <= _PROD_MODE_CLOSE


def select_market_data_mode(
    config: NiftyLtpUatReplayConfig | None = None,
    *,
    now: datetime | None = None,
) -> MarketDataMode:
    """Automatic mode selection (+ optional force_uat_mode override)."""
    cfg = config or NiftyLtpUatReplayConfig()
    if cfg.force_uat_mode:
        logger.info(
            "%s Mode selected = UAT_REPLAY (force_uat_mode=true)",
            UAT_LOG_TAG,
        )
        return MarketDataMode.UAT_REPLAY
    if not cfg.enabled:
        logger.info(
            "%s Mode selected = LIVE (uat_market_replay.enabled=false)",
            LIVE_LOG_TAG,
        )
        return MarketDataMode.LIVE
    if is_drishti_uat_replay_window(now, config=cfg):
        logger.info("%s Mode selected = UAT_REPLAY (off-hours window)", UAT_LOG_TAG)
        return MarketDataMode.UAT_REPLAY
    logger.info("%s Mode selected = LIVE (production / market hours)", LIVE_LOG_TAG)
    return MarketDataMode.LIVE


def build_market_data_provider(
    config: NiftyLtpUatReplayConfig | None = None,
    *,
    now: datetime | None = None,
) -> LiveMarketProvider | ReplayMarketProvider:
    """Factory — Strategy Pattern entry point for DRISHTI."""
    mode = select_market_data_mode(config, now=now)
    if mode is MarketDataMode.UAT_REPLAY:
        return ReplayMarketProvider()
    return LiveMarketProvider()


def get_nifty_ltp_via_provider(
    *,
    max_age_seconds: float | None = None,
    config: NiftyLtpUatReplayConfig | None = None,
) -> float:
    """Identical consumer API regardless of LIVE vs UAT writer."""
    provider = build_market_data_provider(config)
    return provider.get_nifty_ltp(max_age_seconds=max_age_seconds)


def peek_cached_nifty_ltp(*, max_age_seconds: float) -> float | None:
    """Non-raising cache peek (same shared file LIVE and UAT write)."""
    return get_cached_nifty_ltp(max_age_seconds=max_age_seconds)


def live_feed_should_run(config: NiftyLtpUatReplayConfig | None = None) -> bool:
    """False when force_uat_mode owns the cache writer (even in NSE session)."""
    cfg = config or NiftyLtpUatReplayConfig()
    return not bool(cfg.force_uat_mode)


def describe_mode_for_logs(
    config: NiftyLtpUatReplayConfig | None = None,
    *,
    now: datetime | None = None,
) -> str:
    mode = select_market_data_mode(config, now=now)
    tag = UAT_LOG_TAG if mode is MarketDataMode.UAT_REPLAY else LIVE_LOG_TAG
    nse = is_nse_market_session(now)
    return (
        f"{tag} mode={mode.value} force_uat={bool(config and config.force_uat_mode)} "
        f"nse_session={nse} prod_clock={is_production_clock_hours(now)}"
    )
