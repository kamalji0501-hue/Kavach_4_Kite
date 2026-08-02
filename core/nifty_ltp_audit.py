"""NIFTY LTP transport-specific audit logs (WebSocket + REST)."""

from __future__ import annotations

import asyncio
import logging
import threading
import zoneinfo
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("batman.nifty_ltp_audit")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def format_tick_log_line(now: datetime, ltp: float, *, event: str | None = None) -> str:
    """``HH:MM:SS.mmm | LTP`` or with optional event suffix."""
    ts = f"{now.strftime('%H:%M:%S')}.{now.microsecond // 1000:03d}"
    if event:
        return f"{ts} | {ltp:.2f} | {event}\n"
    return f"{ts} | {ltp:.2f}\n"


def append_rest_ltp_log(
    log_dir: Path,
    now: datetime,
    ltp: float,
    *,
    event: str | None = None,
) -> Path:
    """Append one REST poll line to ``rest_ltp_YYYYMMDD.log``."""
    log_dir.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y%m%d")
    log_path = log_dir / f"rest_ltp_{day}.log"
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(format_tick_log_line(now, ltp, event=event))
    return log_path


def append_websocket_ltp_log(
    log_dir: Path,
    now: datetime,
    ltp: float,
    *,
    event: str | None = None,
) -> Path:
    """Append one WebSocket line to ``ws_ltp_YYYYMMDD.log`` (immediate flush)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y%m%d")
    log_path = log_dir / f"ws_ltp_{day}.log"
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(format_tick_log_line(now, ltp, event=event))
    return log_path


class NiftyLtpBatchLogWriter:
    """Buffer WebSocket tick lines and flush to disk periodically."""

    def __init__(
        self,
        log_dir: Path,
        *,
        filename_prefix: str = "ws_ltp",
        flush_interval_seconds: float = 1.0,
    ) -> None:
        self._log_dir = log_dir
        self._filename_prefix = filename_prefix
        self._flush_interval = float(flush_interval_seconds)
        self._buffer: list[str] = []
        self._lock = threading.Lock()
        self._flush_day: str | None = None
        self._running = False
        self._flush_task: asyncio.Task[None] | None = None

    def append_tick(self, now: datetime, ltp: float, *, event: str | None = None) -> None:
        day = now.strftime("%Y%m%d")
        with self._lock:
            self._flush_day = day
            self._buffer.append(format_tick_log_line(now, ltp, event=event))

    def flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            lines = self._buffer
            day = self._flush_day or datetime.now(_IST).strftime("%Y%m%d")
            self._buffer = []
            self._flush_day = None
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"{self._filename_prefix}_{day}.log"
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.writelines(lines)
        except OSError as exc:
            logger.warning("NIFTY batch log flush failed: %s", exc)
            with self._lock:
                self._buffer = lines + self._buffer

    async def start_flush_loop(self) -> None:
        self._running = True
        while self._running:
            await asyncio.sleep(self._flush_interval)
            await asyncio.to_thread(self.flush)

    def stop(self) -> None:
        self._running = False
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self.flush()

    def start(self) -> asyncio.Task[None]:
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._running = True
        self._flush_task = asyncio.create_task(self.start_flush_loop(), name="nifty_ltp_log_flush")
        return self._flush_task
