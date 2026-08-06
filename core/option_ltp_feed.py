"""Background poller: registered + ATO protect option LTPs → daily audit log."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from core.dhan_market_quote import fetch_fno_ltp_rest
from core.nifty_ltp_feed import is_nse_market_session
from core.option_ltp_audit import append_option_ltp_log
from core.option_ltp_watchlist import CachedOptionWatchlist

logger = logging.getLogger("batman.option_ltp_feed")


class OptionLtpAuditService:
    """Poll option LTPs every ``interval_seconds`` (default 2s) during NSE hours."""

    def __init__(
        self,
        *,
        client_code: str,
        token_getter: Callable[[], str | None],
        log_dir: Path,
        workspace_root: Path | None = None,
        interval_seconds: float = 2.0,
        trading_day_check: Callable | None = None,
    ) -> None:
        self.client_code = client_code
        self.token_getter = token_getter
        self.log_dir = log_dir
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.trading_day_check = trading_day_check
        self._watchlist = CachedOptionWatchlist(root=workspace_root, ttl_seconds=60.0)
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._empty_logged = False

    def start(self) -> asyncio.Task[None]:
        if self._task and not self._task.done():
            self._task.cancel()
        self._running = True
        self._task = asyncio.create_task(self.run(), name="option_ltp_audit")
        return self._task

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def run(self) -> None:
        logger.info(
            "Option LTP audit started — interval=%.1fs dir=%s",
            self.interval_seconds,
            self.log_dir,
        )
        try:
            while self._running:
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Option LTP audit tick failed: %s", exc)
                await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            logger.info("Option LTP audit stopped")
            raise

    async def _tick(self) -> None:
        now = datetime.now()
        # Use IST-aware check via is_nse_market_session (expects aware or naive local).
        from zoneinfo import ZoneInfo

        ist_now = datetime.now(ZoneInfo("Asia/Kolkata"))
        if not is_nse_market_session(ist_now, trading_day_check=self.trading_day_check):
            return

        token = self.token_getter()
        if not token or not self.client_code:
            return

        watch = await asyncio.to_thread(self._watchlist.get)
        if not watch.items:
            if not self._empty_logged:
                logger.info(
                    "Option LTP audit idle — no registered legs/protect symbols (%s)",
                    watch.source,
                )
                self._empty_logged = True
            return
        self._empty_logged = False

        try:
            prices = await asyncio.to_thread(
                fetch_fno_ltp_rest,
                self.client_code,
                token,
                watch.security_ids,
            )
        except Exception as exc:
            await asyncio.to_thread(
                append_option_ltp_log,
                self.log_dir,
                ist_now,
                {},
                event=f"error:{str(exc)[:80]}",
            )
            raise

        role_map = watch.role_by_security_id()
        quotes: dict[str, float] = {}
        for sid, px in prices.items():
            role = role_map.get(int(sid))
            if role:
                quotes[role] = float(px)

        await asyncio.to_thread(append_option_ltp_log, self.log_dir, ist_now, quotes)
        try:
            from core.ato_nifty_tick_csv import record_option_quotes

            # Prefer live NIFTY from shared cache when available
            try:
                from core.nifty_ltp_feed import read_nifty_ltp_cache

                snap = read_nifty_ltp_cache()
                if snap is not None and getattr(snap, "ltp", None):
                    from core.ato_nifty_tick_csv import record_nifty_tick

                    record_nifty_tick(ist_now, float(snap.ltp), source="nifty_cache")
            except Exception:
                pass
            record_option_quotes(
                ist_now,
                quotes,
                items=list(watch.items),
                source="option_poll",
            )
        except Exception as csv_exc:
            logger.debug("ATO tick CSV option hook failed: %s", csv_exc)
        logger.debug(
            "Option LTP audit wrote %d/%d quotes source=%s",
            len(quotes),
            len(watch.items),
            watch.source,
        )


def stop_option_ltp_audit(app_bot_data: dict) -> None:
    """Stop service stored on bot_data if present."""
    svc = app_bot_data.pop("option_ltp_audit_service", None)
    if svc is None:
        return
    with contextlib.suppress(Exception):
        svc.stop()
