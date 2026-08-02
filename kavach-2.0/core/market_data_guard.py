"""Cache-first guards — KAVACH must not hammer Dhan when data is already on disk."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger("batman.market_data_guard")

_ENRICH_LOCK = threading.Lock()
_ENRICH_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_ENRICH_TTL_SECONDS = 2.0
_QUOTE_LOCK = threading.Lock()
_LAST_QUOTE_MONO = 0.0
_MIN_QUOTE_INTERVAL_SECONDS = 2.0
# Tradehull option chain with num_strikes=50 is disabled by default (slow, redundant).
_ALLOW_OPTION_CHAIN_FALLBACK = False


def positions_fingerprint(positions: list[dict[str, Any]]) -> str:
    """Stable key for enrich debounce."""
    parts: list[str] = []
    for pos in sorted(positions, key=lambda p: str(p.get("symbol", ""))):
        parts.append(
            f"{pos.get('symbol')}|{pos.get('qty')}|{pos.get('avg_price')}|{pos.get('strike')}"
        )
    blob = "\n".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def get_cached_enrich(fingerprint: str) -> list[dict[str, Any]] | None:
    with _ENRICH_LOCK:
        entry = _ENRICH_CACHE.get(fingerprint)
        if entry is None:
            return None
        ts, data = entry
        if time.monotonic() - ts > _ENRICH_TTL_SECONDS:
            _ENRICH_CACHE.pop(fingerprint, None)
            return None
        return json.loads(json.dumps(data))


def set_cached_enrich(fingerprint: str, positions: list[dict[str, Any]]) -> None:
    with _ENRICH_LOCK:
        _ENRICH_CACHE[fingerprint] = (time.monotonic(), json.loads(json.dumps(positions)))


def allow_live_option_quotes(*, leg_count: int) -> bool:
    """Throttle REST marketfeed — exact legs only, never burst."""
    if leg_count <= 0:
        return False
    global _LAST_QUOTE_MONO
    with _QUOTE_LOCK:
        elapsed = time.monotonic() - _LAST_QUOTE_MONO
        if elapsed < _MIN_QUOTE_INTERVAL_SECONDS:
            logger.debug(
                "live option quote throttled (%.1fs < %.1fs, legs=%d)",
                elapsed,
                _MIN_QUOTE_INTERVAL_SECONDS,
                leg_count,
            )
            return False
        _LAST_QUOTE_MONO = time.monotonic()
    return True


def option_chain_fallback_enabled() -> bool:
    """50-strike Tradehull chain is opt-in only."""
    return _ALLOW_OPTION_CHAIN_FALLBACK


def legs_still_missing_after_fixture(
    positions: list[dict[str, Any]],
    fixture: dict[str, Any] | None,
) -> list[tuple[int, str]]:
    """Return strikes that need live quotes after applying fixture map (no API yet)."""
    from core.nifty_option_expiry import legs_missing_prices
    from core.uat_position_enrich import fixture_price_map

    if not positions:
        return []
    working = [dict(p) for p in positions]
    fmap = fixture_price_map(fixture) if fixture else {}
    for pos in working:
        key = (int(pos.get("strike", 0)), str(pos.get("opt_type", "")).upper())
        if fmap.get(key) is not None and not _has_avg(pos):
            pos["avg_price"] = fmap[key]
    return legs_missing_prices(working)


def _has_avg(pos: dict[str, Any]) -> bool:
    import math

    try:
        px = float(pos.get("avg_price", 0))
        return px > 0 and not math.isnan(px) and not math.isinf(px)
    except (TypeError, ValueError):
        return False


def should_skip_live_quotes(
    positions: list[dict[str, Any]],
    *,
    fixture: dict[str, Any] | None,
) -> tuple[bool, str]:
    """True when enrich can finish without any Dhan/Tradehull call."""
    need = legs_still_missing_after_fixture(positions, fixture)
    if not need:
        return True, "all premiums from broker or fixture"
    return False, f"{len(need)} leg(s) need live quote: {need[:4]}"


def reset_market_data_guard_for_tests() -> None:
    """Clear debounce/throttle state between pytest cases."""
    global _LAST_QUOTE_MONO
    with _ENRICH_LOCK:
        _ENRICH_CACHE.clear()
    with _QUOTE_LOCK:
        _LAST_QUOTE_MONO = 0.0
