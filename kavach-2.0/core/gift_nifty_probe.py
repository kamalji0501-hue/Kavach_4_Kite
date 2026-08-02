"""Off-hours GIFT NIFTY probe — validates DRISHTI/Dhan connectivity when NSE is closed."""

from __future__ import annotations

import asyncio
import logging
import zoneinfo
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from core.gift_nifty_ltp import (
    GiftNiftyCacheSnapshot,
    append_gift_nifty_audit_log,
    fetch_gift_nifty_ltp_rest_with_retry,
    read_gift_nifty_cache,
    write_gift_nifty_cache,
)
from core.nifty_ltp_feed import NiftyLtpFeedConfig, is_nse_market_session, load_feed_config

logger = logging.getLogger("batman.gift_nifty_probe")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


class GiftNiftyProbeService:
    """Poll GIFT NIFTY when NSE cash session is closed — validation only."""

    def __init__(
        self,
        *,
        client_code: str,
        token_getter: Callable[[], str | None],
        config: NiftyLtpFeedConfig | None = None,
        cache_path: Path | None = None,
        log_dir: Path | None = None,
        trading_day_check: Callable[[date], bool] | None = None,
    ) -> None:
        self.client_code = client_code
        self.token_getter = token_getter
        self.config = config or NiftyLtpFeedConfig()
        self.cache_path = cache_path
        self.log_dir = log_dir
        self.trading_day_check = trading_day_check
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._consecutive_failures = 0

    @property
    def poll_interval_seconds(self) -> int:
        return self.config.poll_interval_seconds

    def start(self) -> asyncio.Task[None]:
        if self._task and not self._task.done():
            self._task.cancel()
        self._running = True
        self._task = asyncio.create_task(self.run(), name="gift_nifty_probe")
        return self._task

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def run(self) -> None:
        logger.info(
            "GIFT NIFTY off-hours probe started — poll=%ss (NSE closed only)",
            self.poll_interval_seconds,
        )
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("GIFT NIFTY probe tick error: %s", exc)
            await asyncio.sleep(float(self.poll_interval_seconds))

    async def _tick(self) -> None:
        now = datetime.now(_IST)
        if is_nse_market_session(now, trading_day_check=self.trading_day_check):
            return

        token = self.token_getter()
        if not token or not self.client_code:
            return

        poll_s = self.poll_interval_seconds
        try:
            ltp = await asyncio.to_thread(
                fetch_gift_nifty_ltp_rest_with_retry,
                self.client_code,
                token,
                max_attempts=self.config.rest_max_attempts,
            )
            self._consecutive_failures = 0
            snap = GiftNiftyCacheSnapshot(
                ltp=ltp,
                updated_at=now.isoformat(),
                probe_healthy=True,
                poll_interval_seconds=poll_s,
                consecutive_failures=0,
            )
            write_gift_nifty_cache(snap, self.cache_path)
            if self.config.log_enabled and self.log_dir is not None:
                await asyncio.to_thread(
                    append_gift_nifty_audit_log,
                    self.log_dir,
                    now,
                    ltp,
                    "dhan_rest",
                    event="probe",
                )
            logger.debug("GIFT NIFTY probe LTP=%.2f", ltp)
        except Exception as exc:
            self._consecutive_failures += 1
            prev = read_gift_nifty_cache(self.cache_path)
            snap = GiftNiftyCacheSnapshot(
                ltp=float(prev.ltp if prev else 0.0),
                updated_at=now.isoformat(),
                probe_healthy=False,
                poll_interval_seconds=poll_s,
                consecutive_failures=self._consecutive_failures,
            )
            write_gift_nifty_cache(snap, self.cache_path)
            if self.config.log_enabled and self.log_dir is not None:
                await asyncio.to_thread(
                    append_gift_nifty_audit_log,
                    self.log_dir,
                    now,
                    snap.ltp,
                    "dhan_rest",
                    event=f"error:{str(exc)[:60]}",
                )
            logger.warning(
                "GIFT NIFTY probe fetch failed (%s): %s",
                self._consecutive_failures,
                exc,
            )


def is_gift_probe_running(service: object | None) -> bool:
    if service is None:
        return False
    running = getattr(service, "_running", False)
    task = getattr(service, "_task", None)
    return bool(running and task is not None and not task.done())


def probe_freshness_limit(cfg: NiftyLtpFeedConfig | None) -> float:
    if cfg is None:
        return 6.0
    return cfg.cache_max_age_seconds()
