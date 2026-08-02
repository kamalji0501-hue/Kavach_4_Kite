"""NIFTY LTP cache validation for user-facing DRISHTI pings and shared consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.nifty_ltp_feed import (
    DEFAULT_USER_PING_CRITICAL_AGE_SECONDS,
    DEFAULT_USER_PING_WARNING_AGE_SECONDS,
    NiftyLtpCacheSnapshot,
    NiftyLtpFeedConfig,
)

Severity = Literal["ok", "warning", "critical"]

# Back-compat aliases for tests / imports.
USER_PING_WARNING_AGE_SECONDS = float(DEFAULT_USER_PING_WARNING_AGE_SECONDS)
USER_PING_CRITICAL_AGE_SECONDS = float(DEFAULT_USER_PING_CRITICAL_AGE_SECONDS)


@dataclass(frozen=True)
class UserPingCacheAssessment:
    """Result of checking whether cache may be shown on a DRISHTI NIFTY LTP ping."""

    cache_age_seconds: float
    acceptable_for_display: bool
    requires_live_fetch: bool
    severity: Severity
    warning_message: str
    should_report_incident: bool
    stale_cache_ltp: float | None


@dataclass(frozen=True)
class UserPingThresholds:
    warning_seconds: float
    critical_seconds: float
    feed_max_seconds: float


def resolve_user_ping_thresholds(cfg: NiftyLtpFeedConfig | None) -> UserPingThresholds:
    """Effective warning/critical limits (configurable via LTP Feed Setup)."""
    if cfg is None:
        return UserPingThresholds(
            warning_seconds=float(DEFAULT_USER_PING_WARNING_AGE_SECONDS),
            critical_seconds=float(DEFAULT_USER_PING_CRITICAL_AGE_SECONDS),
            feed_max_seconds=6.0,
        )
    return UserPingThresholds(
        warning_seconds=cfg.effective_user_ping_warning_age_seconds(),
        critical_seconds=cfg.effective_user_ping_critical_age_seconds(),
        feed_max_seconds=cfg.cache_max_age_seconds(),
    )


def feed_freshness_limit(cfg: NiftyLtpFeedConfig | None) -> float:
    """Max cache age for background feed / KAVACH consumers."""
    return resolve_user_ping_thresholds(cfg).feed_max_seconds


def user_ping_display_max_age(cfg: NiftyLtpFeedConfig | None) -> float:
    """Max cache age acceptable when operator taps Nifty LTP during market hours."""
    thresholds = resolve_user_ping_thresholds(cfg)
    return max(thresholds.feed_max_seconds, thresholds.warning_seconds)


def assess_cache_for_user_ping(
    snap: NiftyLtpCacheSnapshot | None,
    cfg: NiftyLtpFeedConfig | None,
    *,
    in_market_session: bool,
    now: datetime | None = None,
) -> UserPingCacheAssessment:
    """Decide if cache is safe to show or must be replaced with a live Dhan fetch."""
    thresholds = resolve_user_ping_thresholds(cfg)
    warn_limit = thresholds.warning_seconds
    crit_limit = thresholds.critical_seconds
    feed_max = thresholds.feed_max_seconds

    if snap is None or snap.ltp <= 0:
        return UserPingCacheAssessment(
            cache_age_seconds=float("inf"),
            acceptable_for_display=False,
            requires_live_fetch=True,
            severity="warning",
            warning_message="No NIFTY LTP in shared cache — fetching live from Dhan.",
            should_report_incident=False,
            stale_cache_ltp=None,
        )

    age = snap.age_seconds(now)
    if age == float("inf"):
        return _critical(
            age,
            float(snap.ltp),
            "Cache timestamp is invalid or unreadable — fetching live.",
        )

    stale_ltp = float(snap.ltp)

    if not in_market_session:
        if age >= crit_limit:
            return _critical(
                age,
                stale_ltp,
                f"Cache is {age:.0f}s old ({_format_age_human(age)}) — "
                f"limit {crit_limit:.0f}s. Must not show stale close; fetching live.",
                crit_limit=crit_limit,
            )
        return UserPingCacheAssessment(
            cache_age_seconds=age,
            acceptable_for_display=False,
            requires_live_fetch=True,
            severity="ok" if age <= feed_max else "warning",
            warning_message=(
                f"Market closed — cache age {age:.0f}s (warn {warn_limit:.0f}s); "
                "fetching live index quote."
                if age > feed_max
                else ""
            ),
            should_report_incident=False,
            stale_cache_ltp=stale_ltp if age > feed_max else None,
        )

    if (
        snap.feed_healthy
        and age <= feed_max
        and snap.is_fresh(feed_max, now=now)
    ):
        return UserPingCacheAssessment(
            cache_age_seconds=age,
            acceptable_for_display=True,
            requires_live_fetch=False,
            severity="ok",
            warning_message="",
            should_report_incident=False,
            stale_cache_ltp=None,
        )

    if age >= crit_limit:
        return _critical(
            age,
            stale_ltp,
            f"Cache is {age:.0f}s old ({_format_age_human(age)}) — "
            f"stale vs live market (limit {crit_limit:.0f}s). "
            "Fetching live from Dhan.",
            crit_limit=crit_limit,
        )

    if age >= warn_limit or not snap.feed_healthy:
        return UserPingCacheAssessment(
            cache_age_seconds=age,
            acceptable_for_display=False,
            requires_live_fetch=True,
            severity="warning",
            warning_message=(
                f"⚠️ <b>Stale cache detected</b> — last cached ₹{stale_ltp:,.2f} "
                f"was {age:.0f}s old (limit {warn_limit:.0f}s). "
                "Fetched live from Dhan below."
            ),
            should_report_incident=False,
            stale_cache_ltp=stale_ltp,
        )

    return UserPingCacheAssessment(
        cache_age_seconds=age,
        acceptable_for_display=False,
        requires_live_fetch=True,
        severity="warning",
        warning_message=(
            f"⚠️ Cache warming — age {age:.0f}s (feed limit {feed_max:.0f}s). "
            "Fetching live from Dhan."
        ),
        should_report_incident=False,
        stale_cache_ltp=stale_ltp,
    )


def _critical(
    age: float,
    stale_ltp: float,
    detail: str,
    *,
    crit_limit: float | None = None,
) -> UserPingCacheAssessment:
    limit_note = f" · limit {crit_limit:.0f}s" if crit_limit is not None else ""
    return UserPingCacheAssessment(
        cache_age_seconds=age,
        acceptable_for_display=False,
        requires_live_fetch=True,
        severity="critical",
        warning_message=(
            f"🔴 <b>Critical — stale NIFTY cache</b>\n"
            f"Cached ₹{stale_ltp:,.2f} · age {age:.0f}s ({_format_age_human(age)}){limit_note}\n"
            f"{detail}"
        ),
        should_report_incident=True,
        stale_cache_ltp=stale_ltp,
    )


def _format_age_human(age_seconds: float) -> str:
    if age_seconds == float("inf"):
        return "unknown"
    if age_seconds >= 86400:
        days = int(age_seconds // 86400)
        return f"{days}d+"
    if age_seconds >= 3600:
        hours = int(age_seconds // 3600)
        mins = int((age_seconds % 3600) // 60)
        return f"{hours}h {mins}m"
    if age_seconds >= 60:
        return f"{int(age_seconds // 60)}m {int(age_seconds % 60)}s"
    return f"{age_seconds:.0f}s"
