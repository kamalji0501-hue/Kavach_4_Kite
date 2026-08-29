"""Kavach Feeder NIFTY collector — persistent Datafeedbot IPC → shared LTP cache."""

from __future__ import annotations

import logging
import threading
import time
import zoneinfo
from datetime import datetime

from core.nifty_ltp_feed import NiftyLtpCacheSnapshot, write_nifty_ltp_cache

logger = logging.getLogger("batman.feeder_nifty_collector")
_IST = zoneinfo.ZoneInfo("Asia/Kolkata")

_stop: threading.Event | None = None
_thread: threading.Thread | None = None


def _seed(ltp: float, source: str) -> None:
    now = datetime.now(_IST)
    snap = NiftyLtpCacheSnapshot(
        ltp=float(ltp),
        updated_at=now.isoformat(),
        last_changed_at=now.isoformat(),
        source=source,
        feed_healthy=True,
        poll_interval_seconds=2,
        consecutive_failures=0,
        unchanged_seconds=0.0,
        collector="feeder",
        collector_pid=None,
    )
    write_nifty_ltp_cache(snap)


def _collector_loop(stop: threading.Event) -> None:
    from core.feeder_ipc import _connect, socket_path

    backoff = 1.0
    while not stop.is_set():
        client = None
        try:
            client = _connect()
            logger.info("Feeder NIFTY collector connected socket=%s", socket_path())
            backoff = 1.0
            while not stop.is_set():
                msg = client.recv(timeout=1.0)
                if not msg or msg.get("type") != "tick":
                    continue
                tick = msg.get("data") or {}
                if not isinstance(tick, dict):
                    continue
                inst = str(tick.get("instrument") or "")
                sid = str(tick.get("broker_id") or tick.get("security_id") or "")
                if inst != "NIFTY_INDEX" and sid != "13":
                    continue
                try:
                    ltp = float(tick.get("ltp") or 0)
                except (TypeError, ValueError):
                    continue
                if ltp <= 0:
                    continue
                src = str(tick.get("source") or "DATAFEEDBOT_WS")
                _seed(ltp, src)
        except Exception as exc:
            logger.warning("Feeder NIFTY collector error: %s — retry in %.1fs", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 15.0)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


def start_feeder_nifty_collector() -> threading.Event:
    """Start background Feeder → NIFTY cache writer (idempotent)."""
    global _stop, _thread
    if _thread is not None and _thread.is_alive():
        return _stop  # type: ignore[return-value]
    _stop = threading.Event()
    _thread = threading.Thread(
        target=_collector_loop,
        args=(_stop,),
        name="feeder-nifty-collector",
        daemon=True,
    )
    _thread.start()
    logger.info("Feeder NIFTY collector thread started")
    return _stop


def stop_feeder_nifty_collector() -> None:
    global _stop, _thread
    if _stop is not None:
        _stop.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=5.0)
    _stop = None
    _thread = None
