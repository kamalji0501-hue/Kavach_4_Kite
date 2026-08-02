"""UAT option premium lookup from DRISHTI option_ltp_YYYYMMDD.log (replay-timed).

During NIFTY UAT replay, live Dhan option quotes stay near today's wall-clock LTP,
so ATO Buy/Sell premiums collapse to the same number. This module reads the
backtest option LTP log at the *replay market time* so SARANSH shows real diffs.
"""

from __future__ import annotations

import logging
import re
import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("batman.option_ltp_uat_lookup")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_LINE_RE = re.compile(
    r"^(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})(?:\.(?P<ms>\d{1,3}))?\s*\|(?P<body>.+)$"
)
_KV_RE = re.compile(r"(?P<role>[a-z0-9_]+)=(?P<px>\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class OptionLtpTick:
    market_time: time
    quotes: dict[str, float]


def _parse_line(line: str) -> OptionLtpTick | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    match = _LINE_RE.match(raw)
    if not match:
        return None
    ms = int((match.group("ms") or "0").ljust(3, "0")[:3])
    market_time = time(
        int(match.group("h")),
        int(match.group("m")),
        int(match.group("s")),
        ms * 1000,
    )
    quotes: dict[str, float] = {}
    for kv in _KV_RE.finditer(match.group("body")):
        quotes[kv.group("role")] = float(kv.group("px"))
    if not quotes:
        return None
    return OptionLtpTick(market_time=market_time, quotes=quotes)


@lru_cache(maxsize=8)
def load_option_ltp_ticks(path_str: str) -> tuple[OptionLtpTick, ...]:
    path = Path(path_str)
    if not path.is_file():
        return ()
    ticks: list[OptionLtpTick] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            tick = _parse_line(line)
            if tick:
                ticks.append(tick)
    except OSError as exc:
        logger.warning("option LTP log read failed (%s): %s", path, exc)
        return ()
    return tuple(ticks)


def resolve_option_ltp_log_path(
    root: Path,
    *,
    day: datetime | None = None,
) -> Path | None:
    """Prefer today's option_ltp log under DRISHTI runtime logs."""
    from core.bot_logging import bot_option_ltp_log_dir

    ts = day or datetime.now(_IST)
    log_dir = bot_option_ltp_log_dir(root, ts=ts)
    candidate = log_dir / f"option_ltp_{ts.strftime('%Y%m%d')}.log"
    if candidate.is_file():
        return candidate
    if log_dir.is_dir():
        files = sorted(log_dir.glob("option_ltp_*.log"), key=lambda p: p.stat().st_mtime)
        if files:
            return files[-1]
    return None


def _seconds(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _as_time(market_time: time | datetime) -> time:
    if isinstance(market_time, datetime):
        return market_time.timetz().replace(tzinfo=None)
    return market_time


def lookup_quotes_at(
    ticks: Sequence[OptionLtpTick],
    market_time: time | datetime,
) -> dict[str, float] | None:
    if not ticks:
        return None
    target = _as_time(market_time)
    target_s = _seconds(target)
    best = min(ticks, key=lambda tick: abs(_seconds(tick.market_time) - target_s))
    return dict(best.quotes)


def role_for_protect_symbol(symbol: str) -> str | None:
    upper = symbol.upper()
    if "-CE" in upper or upper.endswith("CE"):
        return "ce_protect"
    if "-PE" in upper or upper.endswith("PE"):
        return "pe_protect"
    return None


def lookup_protect_premium(
    *,
    symbol: str,
    root: Path,
    replay_market_time: datetime | time | None,
    day: datetime | None = None,
) -> float | None:
    """Return protect-leg premium at replay market time, or None if unavailable."""
    role = role_for_protect_symbol(symbol)
    if not role or replay_market_time is None:
        return None
    path = resolve_option_ltp_log_path(root, day=day)
    if path is None:
        return None
    ticks = load_option_ltp_ticks(str(path.resolve()))
    quotes = lookup_quotes_at(ticks, replay_market_time)
    if not quotes:
        return None
    raw = quotes.get(role)
    if raw is None:
        return None
    value = float(raw)
    return value if value > 0 else None


def replay_market_time_from_cache(root: Path | None = None) -> datetime | None:
    """Read replay market time stamped into the shared NIFTY LTP cache."""
    try:
        from core.batman_mode import nifty_ltp_cache_path, workspace_root
        from core.nifty_ltp_feed import read_nifty_ltp_cache

        cache_root = root or workspace_root()
        snap = read_nifty_ltp_cache(nifty_ltp_cache_path(cache_root))
        if snap is None or str(getattr(snap, "source", "")) != "uat_replay":
            return None
        raw = getattr(snap, "replay_market_time", None)
        if not raw:
            return None
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_IST)
        return dt.astimezone(_IST)
    except Exception as exc:
        logger.debug("replay market time from cache failed: %s", exc)
        return None
