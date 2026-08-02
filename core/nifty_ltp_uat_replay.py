"""DRISHTI UAT Market Replay — emit stored NIFTY ticks into the shared LTP cache.

Production WebSocket/REST collectors are unchanged. This module only runs outside
the NSE cash session (and within the configured UAT window) so off-hours
end-to-end testing can reuse captured ``ws_ltp_*.log`` / ``rest_ltp_*.log`` files.
"""

from __future__ import annotations

import asyncio
import logging
import re
import zoneinfo
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from core.nifty_ltp_feed import (
    NiftyLtpCacheSnapshot,
    compute_unchanged_seconds,
    default_cache_path,
    is_nse_market_session,
    write_nifty_ltp_cache,
)

logger = logging.getLogger("batman.nifty_ltp_uat_replay")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
UAT_LOG_TAG = "[DRISHTI UAT]"
CACHE_SOURCE = "uat_replay"

REPLAY_SPEED_REALTIME = "realtime"
REPLAY_SPEED_FAST = "fast"
REPLAY_SPEED_ULTRA = "ultra"
REPLAY_SPEED_OPTIONS = (
    REPLAY_SPEED_REALTIME,
    REPLAY_SPEED_FAST,
    REPLAY_SPEED_ULTRA,
)
DEFAULT_REPLAY_SPEED = REPLAY_SPEED_FAST

# Off-hours UAT window (IST). Live NSE feed remains 09:15–15:30.
_DEFAULT_UAT_START = time(15, 31)
_DEFAULT_UAT_END = time(8, 55)

_TICK_LINE_RE = re.compile(
    r"^(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{1,3})\s*\|\s*(?P<ltp>[\d.]+)"
)

_SPEED_SCALE = {
    REPLAY_SPEED_REALTIME: 1.0,
    # fast = 3x wall-clock (1s stored gap → ~333ms sleep)
    REPLAY_SPEED_FAST: 1.0 / 3.0,
    REPLAY_SPEED_ULTRA: 0.0,
}


@dataclass(frozen=True)
class ReplayTick:
    """One stored tick — wall-clock date is attached when loading a day file."""

    stored_at: datetime
    ltp: float


@dataclass
class NiftyLtpUatReplayConfig:
    """Operator settings for DRISHTI UAT Market Replay."""

    enabled: bool = True
    force_uat_mode: bool = False
    replay_speed: str = DEFAULT_REPLAY_SPEED
    loop: bool = True
    window_start: time = _DEFAULT_UAT_START
    window_end: time = _DEFAULT_UAT_END
    prefer_websocket_logs: bool = True
    min_ticks: int = 10
    poll_interval_seconds: int = 1

    def __post_init__(self) -> None:
        if self.replay_speed not in REPLAY_SPEED_OPTIONS:
            raise ValueError(f"replay_speed must be one of {REPLAY_SPEED_OPTIONS}")
        if self.min_ticks < 1:
            raise ValueError("min_ticks must be >= 1")
        if self.poll_interval_seconds < 1:
            raise ValueError("poll_interval_seconds must be >= 1")

    def speed_scale(self) -> float:
        return float(_SPEED_SCALE[self.replay_speed])

    def speed_label(self) -> str:
        labels = {
            REPLAY_SPEED_REALTIME: "Real-time (1s = 1s)",
            REPLAY_SPEED_FAST: "Fast (3x — 1s = ~333ms)",
            REPLAY_SPEED_ULTRA: "Ultra-fast (as fast as possible)",
        }
        return labels.get(self.replay_speed, self.replay_speed)

    def speed_multiplier_label(self) -> str:
        """Short operator label: 1x / 3x / max."""
        if self.replay_speed == REPLAY_SPEED_REALTIME:
            return "1x"
        if self.replay_speed == REPLAY_SPEED_FAST:
            return "3x"
        if self.replay_speed == REPLAY_SPEED_ULTRA:
            return "max"
        return self.replay_speed


@dataclass(frozen=True)
class UatReplayProgress:
    """Observability snapshot for the tick currently (last) emitted to the cache."""

    ltp: float
    replay_market_time: datetime
    current_system_time: datetime
    tick_index: int
    tick_total: int
    replay_speed: str
    speed_multiplier: str
    source_file: str

    @property
    def progress_percent(self) -> float:
        if self.tick_total <= 0:
            return 0.0
        return min(100.0, 100.0 * float(self.tick_index) / float(self.tick_total))

    @property
    def market_offset_seconds(self) -> float:
        return (self.current_system_time - self.replay_market_time).total_seconds()


def format_clock_ampm(when: datetime) -> str:
    """``09:47:12 AM`` style for Telegram/UAT cards."""
    return when.astimezone(_IST).strftime("%I:%M:%S %p").lstrip("0")


def format_market_offset(seconds: float) -> str:
    """``+10h 55m 06s`` / ``-0h 05m 12s``."""
    sign = "+" if seconds >= 0 else "-"
    total = int(abs(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{sign}{hours}h {minutes:02d}m {secs:02d}s"


def format_uat_time_block(progress: UatReplayProgress, *, html_escape: bool = False) -> str:
    """Multi-line Replay/Current/Progress/Speed/Offset block for Telegram."""
    replay_s = format_clock_ampm(progress.replay_market_time)
    current_s = format_clock_ampm(progress.current_system_time)
    offset_s = format_market_offset(progress.market_offset_seconds)
    prog = f"{progress.progress_percent:.1f}%"
    speed = progress.speed_multiplier
    if html_escape:
        import html as _html

        replay_s = _html.escape(replay_s)
        current_s = _html.escape(current_s)
        offset_s = _html.escape(offset_s)
        prog = _html.escape(prog)
        speed = _html.escape(speed)
    return (
        f"Replay Market Time: {replay_s}\n"
        f"Current Time:       {current_s}\n"
        f"Replay Progress:    {prog}\n"
        f"Replay Speed:       {speed}\n"
        f"Market Offset:      {offset_s}"
    )


def parse_tick_log_line(line: str, *, day: date) -> ReplayTick | None:
    """Parse ``HH:MM:SS.mmm | LTP`` (optional event suffix) into a ReplayTick."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    match = _TICK_LINE_RE.match(text)
    if not match:
        return None
    ms = int(match.group("ms").ljust(3, "0")[:3])
    stored_at = datetime(
        day.year,
        day.month,
        day.day,
        int(match.group("h")),
        int(match.group("m")),
        int(match.group("s")),
        ms * 1000,
        tzinfo=_IST,
    )
    return ReplayTick(stored_at=stored_at, ltp=float(match.group("ltp")))


def day_from_tick_log_path(path: Path) -> date | None:
    """Extract YYYYMMDD from ``ws_ltp_YYYYMMDD.log`` / ``rest_ltp_YYYYMMDD.log``."""
    stem = path.stem
    for prefix in ("ws_ltp_", "rest_ltp_"):
        if stem.startswith(prefix):
            raw = stem[len(prefix) :]
            try:
                return datetime.strptime(raw, "%Y%m%d").date()
            except ValueError:
                return None
    return None


def load_ticks_from_log(path: Path) -> list[ReplayTick]:
    """Load all valid ticks from a DRISHTI transport audit log."""
    day = day_from_tick_log_path(path)
    if day is None:
        logger.warning("%s Cannot derive day from source file %s", UAT_LOG_TAG, path)
        return []
    ticks: list[ReplayTick] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tick = parse_tick_log_line(line, day=day)
                if tick is not None:
                    ticks.append(tick)
    except OSError as exc:
        logger.warning("%s Failed reading source file %s: %s", UAT_LOG_TAG, path, exc)
        return []
    return ticks


def replay_delay_seconds(
    previous: ReplayTick | None,
    current: ReplayTick,
    *,
    speed: str,
) -> float:
    """Sleep duration between emitting *previous* and *current*."""
    if previous is None:
        return 0.0
    raw_delta = max(0.0, (current.stored_at - previous.stored_at).total_seconds())
    scale = _SPEED_SCALE.get(speed, _SPEED_SCALE[DEFAULT_REPLAY_SPEED])
    if scale <= 0.0:
        return 0.0
    # Cap pathological gaps (e.g. lunch / restart holes) so UAT does not stall.
    capped = min(raw_delta, 5.0)
    return capped * scale


def is_drishti_uat_replay_window(
    now: datetime | None = None,
    *,
    config: NiftyLtpUatReplayConfig | None = None,
    trading_day_check: Callable[[date], bool] | None = None,
) -> bool:
    """True when DRISHTI may run UAT replay.

    - ``force_uat_mode=True`` → always (even during NSE hours).
    - Else overnight window ``window_start``→``window_end`` (e.g. 15:31→08:55),
      never overlapping live NSE cash session (09:15–15:30) unless forced.
    """
    cfg = config or NiftyLtpUatReplayConfig()
    if not cfg.enabled:
        return False
    if cfg.force_uat_mode:
        return True
    now = now or datetime.now(_IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    else:
        now = now.astimezone(_IST)

    if is_nse_market_session(now, trading_day_check=trading_day_check):
        return False

    t = now.time()
    start = cfg.window_start
    end = cfg.window_end
    if start <= end:
        # Same-day window (unusual); keep for config flexibility.
        return start <= t <= end
    # Overnight window: after start OR before/at end.
    return t >= start or t <= end


def _iter_candidate_tick_logs(
    logs_root: Path,
    *,
    prefer_websocket: bool = True,
) -> list[Path]:
    patterns = (
        ("**/nifty_websocket_ltp/ws_ltp_*.log", "**/nifty_rest_ltp/rest_ltp_*.log")
        if prefer_websocket
        else ("**/nifty_rest_ltp/rest_ltp_*.log", "**/nifty_websocket_ltp/ws_ltp_*.log")
    )
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        try:
            matches = sorted(
                logs_root.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            continue
        for path in matches:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(path)
    return found


def resolve_replay_source_file(
    workspace_root: Path | None = None,
    *,
    config: NiftyLtpUatReplayConfig | None = None,
    logs_root: Path | None = None,
) -> Path | None:
    """Pick the newest captured tick log with enough ticks (WS preferred)."""
    cfg = config or NiftyLtpUatReplayConfig()
    if logs_root is None:
        from core.batman_mode import log_runtime_root, workspace_root as _ws

        root = workspace_root or _ws()
        try:
            logs_root = log_runtime_root(root)
        except Exception:
            logs_root = root / "logs_runtime"
    candidates = _iter_candidate_tick_logs(
        logs_root,
        prefer_websocket=cfg.prefer_websocket_logs,
    )
    for path in candidates:
        try:
            if path.stat().st_size <= 0:
                continue
        except OSError:
            continue
        ticks = load_ticks_from_log(path)
        if len(ticks) >= cfg.min_ticks:
            return path
    return None


def load_uat_replay_config_from_params(params: dict | None) -> NiftyLtpUatReplayConfig:
    """Build config from ``telegram/bots/drishti/params.json`` → ``uat_market_replay``."""
    raw = (params or {}).get("uat_market_replay") or {}
    if not isinstance(raw, dict):
        return NiftyLtpUatReplayConfig()

    def _parse_hhmm(value: object, default: time) -> time:
        text = str(value or "").strip()
        if not text:
            return default
        try:
            hour_s, minute_s = text.split(":", 1)
            return time(int(hour_s), int(minute_s))
        except (TypeError, ValueError):
            return default

    speed = str(raw.get("replay_speed", DEFAULT_REPLAY_SPEED)).strip().lower()
    if speed not in REPLAY_SPEED_OPTIONS:
        speed = DEFAULT_REPLAY_SPEED
    return NiftyLtpUatReplayConfig(
        enabled=bool(raw.get("enabled", True)),
        force_uat_mode=bool(raw.get("force_uat_mode", False)),
        replay_speed=speed,
        loop=bool(raw.get("loop", True)),
        window_start=_parse_hhmm(raw.get("window_start"), _DEFAULT_UAT_START),
        window_end=_parse_hhmm(raw.get("window_end"), _DEFAULT_UAT_END),
        prefer_websocket_logs=bool(raw.get("prefer_websocket_logs", True)),
        min_ticks=int(raw.get("min_ticks", 10)),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 1)),
    )


class NiftyLtpUatReplayService:
    """Background replay writer — same shared cache consumers already read."""

    def __init__(
        self,
        *,
        config: NiftyLtpUatReplayConfig,
        source_file: Path,
        ticks: Sequence[ReplayTick],
        cache_path: Path | None = None,
        on_started: Callable[[], None] | None = None,
        on_stopped: Callable[[], None] | None = None,
        trading_day_check: Callable[[date], bool] | None = None,
    ) -> None:
        if not ticks:
            raise ValueError("ticks must not be empty")
        self.config = config
        self.source_file = source_file
        self.ticks = list(ticks)
        self.cache_path = cache_path or default_cache_path()
        self.on_started = on_started
        self.on_stopped = on_stopped
        self.trading_day_check = trading_day_check
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._started_notified = False
        self._tick_index = 0
        self._last_ltp: float | None = None
        self._last_changed_at: datetime | None = None
        self._last_emitted_tick: ReplayTick | None = None
        self._last_emitted_wall: datetime | None = None
        self.started_at: datetime | None = None

    def progress_snapshot(self, *, now: datetime | None = None) -> UatReplayProgress | None:
        """Progress for the last tick written to the shared cache (exact LTP+time pair)."""
        tick = self._last_emitted_tick
        if tick is None:
            return None
        wall = now or self._last_emitted_wall or datetime.now(_IST)
        if wall.tzinfo is None:
            wall = wall.replace(tzinfo=_IST)
        return UatReplayProgress(
            ltp=float(tick.ltp),
            replay_market_time=tick.stored_at,
            current_system_time=wall.astimezone(_IST),
            tick_index=int(self._tick_index),
            tick_total=len(self.ticks),
            replay_speed=self.config.replay_speed,
            speed_multiplier=self.config.speed_multiplier_label(),
            source_file=self.source_file.name,
        )

    def start(self) -> asyncio.Task[None]:
        if self._task and not self._task.done():
            self._task.cancel()
        self._running = True
        self._task = asyncio.create_task(self.run(), name="nifty_ltp_uat_replay")
        return self._task

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def run(self) -> None:
        self.started_at = datetime.now(_IST)
        logger.info(
            "%s Replaying source file=%s ticks=%s speed=%s loop=%s",
            UAT_LOG_TAG,
            self.source_file,
            len(self.ticks),
            self.config.replay_speed,
            self.config.loop,
        )
        if self.on_started is not None and not self._started_notified:
            self._started_notified = True
            try:
                self.on_started()
            except Exception as exc:
                logger.warning("%s on_started hook failed: %s", UAT_LOG_TAG, exc)

        try:
            while self._running:
                if not is_drishti_uat_replay_window(
                    config=self.config,
                    trading_day_check=self.trading_day_check,
                ):
                    logger.info("%s Window closed — stopping replay", UAT_LOG_TAG)
                    break
                await self._emit_one()
                if self._tick_index >= len(self.ticks):
                    if not self.config.loop:
                        logger.info("%s Replay finished (no loop)", UAT_LOG_TAG)
                        break
                    logger.info(
                        "%s Replay completion — looping from start "
                        "(position reset, tick_count=%s)",
                        UAT_LOG_TAG,
                        len(self.ticks),
                    )
                    self._tick_index = 0
                    self._last_ltp = None
                    self._last_changed_at = None
                    self._last_emitted_tick = None
                    self._last_emitted_wall = None
        except asyncio.CancelledError:
            logger.info(
                "%s Replay cancelled (graceful shutdown) position=%s/%s",
                UAT_LOG_TAG,
                self._tick_index,
                len(self.ticks),
            )
        finally:
            self._running = False
            logger.info(
                "%s Replay stopped — final position=%s/%s recovery=idle",
                UAT_LOG_TAG,
                self._tick_index,
                len(self.ticks),
            )
            if self._started_notified and self.on_stopped is not None:
                try:
                    self.on_stopped()
                except Exception as exc:
                    logger.warning("%s on_stopped hook failed: %s", UAT_LOG_TAG, exc)
                self._started_notified = False

    async def _emit_one(self) -> None:
        idx = self._tick_index
        if idx >= len(self.ticks):
            return
        current = self.ticks[idx]
        previous = self.ticks[idx - 1] if idx > 0 else None
        delay = replay_delay_seconds(
            previous,
            current,
            speed=self.config.replay_speed,
        )
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            # Yield so Telegram / other coroutines stay responsive.
            await asyncio.sleep(0)

        if not self._running:
            return

        now = datetime.now(_IST)
        unchanged, last_changed = compute_unchanged_seconds(
            previous_ltp=self._last_ltp,
            new_ltp=current.ltp,
            last_changed_at=self._last_changed_at,
            now=now,
        )
        write_nifty_ltp_cache(
            NiftyLtpCacheSnapshot(
                ltp=float(current.ltp),
                updated_at=now.isoformat(),
                last_changed_at=last_changed.isoformat(),
                source=CACHE_SOURCE,
                feed_healthy=True,
                poll_interval_seconds=self.config.poll_interval_seconds,
                consecutive_failures=0,
                unchanged_seconds=unchanged,
                collector="drishti",
                replay_market_time=current.stored_at.isoformat(),
            ),
            self.cache_path,
        )
        self._last_ltp = current.ltp
        self._last_changed_at = last_changed
        self._last_emitted_tick = current
        self._last_emitted_wall = now
        self._tick_index = idx + 1
        progress = self.progress_snapshot(now=now)
        prog_pct = progress.progress_percent if progress else 0.0
        log_line = (
            f"{UAT_LOG_TAG} Replay Time = {current.stored_at.strftime('%H:%M:%S')} "
            f"| Current Time = {now.strftime('%H:%M:%S')} "
            f"| LTP = {current.ltp:.2f} "
            f"| Progress = {prog_pct:.1f}% "
            f"| Speed = {self.config.speed_multiplier_label()} "
            f"| index={idx + 1}/{len(self.ticks)}"
        )
        if idx == 0 or idx % 500 == 0:
            logger.info("%s", log_line)
        else:
            logger.debug("%s", log_line)


def is_uat_replay_task_running(service: object | None) -> bool:
    if service is None:
        return False
    running = getattr(service, "_running", False)
    task = getattr(service, "_task", None)
    return bool(running and task is not None and not task.done())


def build_uat_replay_service(
    *,
    config: NiftyLtpUatReplayConfig,
    workspace_root: Path | None = None,
    cache_path: Path | None = None,
    on_started: Callable[[], None] | None = None,
    on_stopped: Callable[[], None] | None = None,
    trading_day_check: Callable[[date], bool] | None = None,
) -> NiftyLtpUatReplayService | None:
    """Resolve source file + ticks and construct a replay service, or None."""
    source = resolve_replay_source_file(workspace_root, config=config)
    if source is None:
        logger.warning(
            "%s No suitable tick log found under logs_runtime — cannot start replay",
            UAT_LOG_TAG,
        )
        return None
    ticks = load_ticks_from_log(source)
    if len(ticks) < config.min_ticks:
        logger.warning(
            "%s Source file %s has only %s ticks (min=%s)",
            UAT_LOG_TAG,
            source,
            len(ticks),
            config.min_ticks,
        )
        return None
    logger.info("%s Source File = %s (%s ticks)", UAT_LOG_TAG, source, len(ticks))
    return NiftyLtpUatReplayService(
        config=config,
        source_file=source,
        ticks=ticks,
        cache_path=cache_path,
        on_started=on_started,
        on_stopped=on_stopped,
        trading_day_check=trading_day_check,
    )
