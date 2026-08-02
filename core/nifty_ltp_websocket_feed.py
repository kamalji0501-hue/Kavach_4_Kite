"""In-process Dhan WebSocket v2 NIFTY feed — writes shared LTP cache.

``NiftyLtpWebSocketFeedService`` runs inside DRISHTI when ``feed_mode=websocket``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import zoneinfo
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.dhan_ws_tick import extract_ltp_from_ws_tick
from core.exceptions import BrokerAuthError
from core.nifty_ltp import is_auth_error, is_rate_limit_error
from core.nifty_ltp_audit import NiftyLtpBatchLogWriter
from core.nifty_ltp_feed import (
    FEED_MODE_WEBSOCKET,
    FeedAlertHooks,
    NiftyLtpCacheSnapshot,
    NiftyLtpFeedConfig,
    _default_websocket_ltp_log_dir,
    _FeedRuntime,
    compute_unchanged_seconds,
    default_cache_path,
    is_nse_market_session,
    is_within_feed_startup_grace,
    mark_transport_started,
    run_feed_stale_watchdog,
    write_nifty_ltp_cache,
)

logger = logging.getLogger("batman.nifty_ltp_websocket_feed")


_IST = zoneinfo.ZoneInfo("Asia/Kolkata")

_SOURCE = "dhan_websocket"

_NIFTY_INSTRUMENT = (0, "13", 15)

_WS_LOG_FLUSH_SECONDS = 1.0


async def _disconnect_feed(feed: Any) -> None:

    try:

        if hasattr(feed, "disconnect"):

            await feed.disconnect()

        elif hasattr(feed, "close"):

            await feed.close()

    except Exception:

        pass


def _mark_cache_unhealthy(
    *,
    cache_path: Path,
    last_ltp: float | None,
    last_changed_at: datetime | None,
    poll_interval: int,
    failures: int,
) -> None:

    now = datetime.now(_IST)

    write_nifty_ltp_cache(
        NiftyLtpCacheSnapshot(
            ltp=float(last_ltp or 0.0),
            updated_at=now.isoformat(),
            last_changed_at=(last_changed_at or now).isoformat(),
            source=_SOURCE,
            feed_healthy=False,
            poll_interval_seconds=poll_interval,
            consecutive_failures=failures,
        ),
        cache_path,
    )


class NiftyLtpWebSocketFeedService:
    """In-process WebSocket feed — sole writer to ``nifty_ltp_cache.json``."""

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
        reconnect_base_seconds: float = 2.0,
        tick_timeout_seconds: float = 30.0,
    ) -> None:

        if not config.is_websocket_mode():

            raise ValueError(f"feed_mode must be {FEED_MODE_WEBSOCKET!r}")

        self.client_code = client_code

        self.token_getter = token_getter

        self.config = config

        self.hooks = hooks

        self.cache_path = cache_path or default_cache_path()

        self.log_dir = log_dir or _default_websocket_ltp_log_dir()

        self.trading_day_check = trading_day_check

        self.reconnect_base_seconds = reconnect_base_seconds

        self.tick_timeout_seconds = tick_timeout_seconds

        self._runtime = _FeedRuntime()

        self._running = False

        self._task: asyncio.Task[None] | None = None

        self._log_writer = NiftyLtpBatchLogWriter(
            self.log_dir,
            filename_prefix="ws_ltp",
            flush_interval_seconds=_WS_LOG_FLUSH_SECONDS,
        )

        self._reconnect_count = 0

    def start(self) -> asyncio.Task[None]:

        if self._task and not self._task.done():

            self._task.cancel()

        self._running = True

        self._task = asyncio.create_task(self.run(), name="nifty_ltp_websocket_feed")

        return self._task

    def stop(self) -> None:

        self._running = False

        if self._task and not self._task.done():

            self._task.cancel()

        self._log_writer.stop()

    async def run(self) -> None:

        logger.info(
            "NIFTY WebSocket feed started — consumer_stale=%ss log_flush=%ss",
            self.config.websocket_stale_critical_seconds,
            _WS_LOG_FLUSH_SECONDS,
        )

        mark_transport_started(self._runtime)

        flush_task = self._log_writer.start()

        watchdog = asyncio.create_task(
            run_feed_stale_watchdog(
                config=self.config,
                runtime=self._runtime,
                hooks=self.hooks,
                is_running=lambda: self._running,
                trading_day_check=self.trading_day_check,
            ),
            name="nifty_ws_stale_watchdog",
        )

        try:

            await self._collector_loop()

        finally:

            watchdog.cancel()

            with contextlib.suppress(asyncio.CancelledError):

                await watchdog

            flush_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):

                await flush_task

            self._log_writer.stop()

    async def _collector_loop(self) -> None:

        backoff = self.reconnect_base_seconds

        last_ltp: float | None = None

        last_changed_at: datetime | None = None

        while self._running:

            if not is_nse_market_session(
                datetime.now(_IST), trading_day_check=self.trading_day_check
            ):

                await asyncio.sleep(5.0)

                continue

            token = self.token_getter()

            if not token or not self.client_code:

                await asyncio.sleep(2.0)

                continue

            now = datetime.now(_IST)
            rt = self._runtime
            if rt.rate_limit_until is not None and now < rt.rate_limit_until:
                cooldown = (rt.rate_limit_until - now).total_seconds()
                logger.info(
                    "NIFTY WebSocket rate limited — waiting %.0fs before reconnect",
                    cooldown,
                )
                await asyncio.sleep(min(cooldown, 5.0))
                continue

            feed = None

            try:

                from dhanhq import DhanContext
                from dhanhq.marketfeed import MarketFeed

            except ImportError as exc:

                raise RuntimeError(
                    "dhanhq package not installed. Run: pip install dhanhq==2.2.0rc1"
                ) from exc

            try:

                context = DhanContext(client_id=self.client_code, access_token=token)

                feed = MarketFeed(
                    dhan_context=context,
                    instruments=[_NIFTY_INSTRUMENT],
                    version="v2",
                )

                await feed.connect()

                logger.info("NIFTY WebSocket feed connected")
                mark_transport_started(self._runtime)

                backoff = self.reconnect_base_seconds

                session_token = self.token_getter()

                while self._running:

                    if not is_nse_market_session(
                        datetime.now(_IST), trading_day_check=self.trading_day_check
                    ):

                        break

                    current_token = self.token_getter()
                    if not current_token or current_token != session_token:
                        logger.info("NIFTY WebSocket token changed or missing — reconnecting")
                        break

                    tick = await asyncio.wait_for(
                        feed.get_instrument_data(),
                        timeout=self.tick_timeout_seconds,
                    )

                    ltp = extract_ltp_from_ws_tick(tick)
                    if ltp is None:
                        continue

                    now = datetime.now(_IST)

                    unchanged_seconds, last_changed_at = compute_unchanged_seconds(
                        previous_ltp=last_ltp,
                        new_ltp=ltp,
                        last_changed_at=last_changed_at,
                        now=now,
                    )

                    if last_ltp is None or ltp != last_ltp:

                        last_changed_at = now

                        unchanged_seconds = 0.0

                    last_ltp = ltp

                    self._runtime.last_ltp = ltp

                    self._runtime.last_update_at = now

                    self._runtime.consecutive_failures = 0

                    self._runtime.rate_limit_until = None

                    if self._runtime.fetch_jagran_sent and self.hooks is not None:

                        await self.hooks.on_fetch_recovered()

                    self._runtime.fetch_jagran_sent = False

                    snap = NiftyLtpCacheSnapshot(
                        ltp=ltp,
                        updated_at=now.isoformat(),
                        last_changed_at=last_changed_at.isoformat(),
                        source=_SOURCE,
                        feed_healthy=True,
                        poll_interval_seconds=self.config.poll_interval_seconds,
                        consecutive_failures=0,
                        unchanged_seconds=unchanged_seconds,
                    )

                    write_nifty_ltp_cache(snap, self.cache_path)

                    if self.config.log_enabled:

                        self._log_writer.append_tick(now, ltp)

            except asyncio.CancelledError:

                raise

            except Exception as exc:

                now = datetime.now(_IST)
                in_session = is_nse_market_session(now, trading_day_check=self.trading_day_check)
                in_grace = is_within_feed_startup_grace(
                    now,
                    grace_seconds=self.config.websocket_startup_grace_seconds,
                    trading_day_check=self.trading_day_check,
                )

                if not in_session:
                    await asyncio.sleep(5.0)
                    continue

                exc_str = str(exc)
                if is_auth_error(exc_str) or isinstance(exc, BrokerAuthError):
                    logger.error("NIFTY WebSocket auth failure (no retry): %s", exc_str[:160])
                    if self.hooks is not None and not self._runtime.fetch_jagran_sent:
                        self._runtime.fetch_jagran_sent = True
                        await self.hooks.on_auth_failure(error=exc_str)
                    if self.config.log_enabled:
                        self._log_writer.append_tick(
                            now,
                            float(last_ltp or 0.0),
                            event="auth_error",
                        )
                    await asyncio.sleep(60.0)
                    continue
                if is_rate_limit_error(exc_str):
                    cooldown = self.config.rate_limit_cooldown_seconds
                    self._runtime.rate_limit_until = now + timedelta(seconds=cooldown)
                    self._runtime.last_update_at = now
                    logger.warning(
                        "NIFTY WebSocket rate limited — cooldown %.0fs "
                        "(failures=%s, not escalated): %s",
                        cooldown,
                        self._runtime.consecutive_failures,
                        exc_str[:120],
                    )
                    if self.config.log_enabled:
                        self._log_writer.append_tick(
                            now,
                            float(last_ltp or 0.0),
                            event="rate_limit",
                        )
                    await asyncio.sleep(cooldown)
                    continue

                self._runtime.consecutive_failures += 1

                if in_grace:
                    logger.info("NIFTY WebSocket feed error during startup grace: %s", exc)
                else:
                    logger.warning("NIFTY WebSocket feed error: %s", exc)
                    _mark_cache_unhealthy(
                        cache_path=self.cache_path,
                        last_ltp=last_ltp,
                        last_changed_at=last_changed_at,
                        poll_interval=self.config.poll_interval_seconds,
                        failures=self._runtime.consecutive_failures,
                    )
                    threshold = self.config.fetch_failure_jagran_threshold
                    if (
                        self.hooks is not None
                        and self._runtime.consecutive_failures >= threshold
                        and not self._runtime.fetch_jagran_sent
                    ):
                        self._runtime.fetch_jagran_sent = True
                        await self.hooks.on_fetch_failure(
                            failures=self._runtime.consecutive_failures,
                            threshold=threshold,
                            error=str(exc),
                        )

                if self.config.log_enabled:
                    self._log_writer.append_tick(
                        now,
                        float(last_ltp or 0.0),
                        event=f"error:{str(exc)[:60]}",
                    )

                if not self._running:
                    break

                self._reconnect_count += 1

                if self.config.log_enabled:
                    self._log_writer.append_tick(
                        now,
                        float(last_ltp or 0.0),
                        event="reconnect",
                    )

                await asyncio.sleep(backoff)

                backoff = min(backoff * 2.0, 60.0)

            finally:

                if feed is not None:

                    await _disconnect_feed(feed)
