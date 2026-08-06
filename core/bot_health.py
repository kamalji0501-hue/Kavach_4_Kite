"""Per-bot health snapshots on disk — independent processes, no cross-import."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("batman.bot_health")

_IST = ZoneInfo("Asia/Kolkata")
_ROOT = Path(__file__).resolve().parent.parent


def health_path(root: Path, bot: str) -> Path:
    try:
        from core.batman_mode import data_root

        return data_root(root) / "runtime" / bot.lower() / "health.json"
    except Exception:
        return root / "data" / "runtime" / bot.lower() / "health.json"


def write_bot_health(
    root: Path,
    bot: str,
    *,
    status: str = "running",
    extra: dict[str, Any] | None = None,
) -> Path:
    """Atomically write ``data/runtime/{bot}/health.json``."""
    path = health_path(root, bot)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "bot": bot.lower(),
        "status": status,
        "pid": os.getpid(),
        "updated_at": datetime.now(_IST).isoformat(),
    }
    if extra:
        payload.update(extra)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".health.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return path


def read_bot_health(root: Path, bot: str) -> dict[str, Any] | None:
    path = health_path(root, bot)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else None
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("health read failed for %s: %s", bot, exc)
        return None


def health_age_seconds(health: dict[str, Any], *, now: datetime | None = None) -> float | None:
    """Seconds since ``updated_at`` in a health payload."""
    updated = health.get("updated_at")
    if not updated:
        return None
    now = now or datetime.now(_IST)
    try:
        ts = datetime.fromisoformat(str(updated))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_IST)
        return max(0.0, (now - ts.astimezone(_IST)).total_seconds())
    except (TypeError, ValueError):
        return None


def health_confirms_running(
    root: Path,
    bot: str,
    pids: tuple[int, ...],
    *,
    max_age_seconds: float = 90.0,
) -> tuple[bool, float | None]:
    """True when health.json is fresh and reports ``running`` for a known PID."""
    health = read_bot_health(root, bot)
    if health is None:
        return False, None
    age = health_age_seconds(health)
    if age is None or age > max_age_seconds:
        return False, age
    if str(health.get("status", "")).lower() != "running":
        return False, age
    hp = health.get("pid")
    if hp is None:
        return False, age
    try:
        hp_int = int(hp)
    except (TypeError, ValueError):
        return False, age
    if hp_int in pids:
        return True, age
    from scripts.stop_bot_common import find_pids_by_commandline

    marker = f"run_{bot.lower()}.py"
    if hp_int in find_pids_by_commandline(marker):
        return True, age
    return False, age


def start_health_heartbeat(
    root: Path,
    bot: str,
    *,
    interval_seconds: float = 30.0,
    extra_provider: Callable[[], dict[str, Any]] | None = None,
) -> threading.Event:
    """Background thread updating health.json until *stop* is set."""
    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(interval_seconds):
            try:
                extra = extra_provider() if extra_provider else {}
                write_bot_health(root, bot, extra=extra)
            except Exception as exc:
                logger.debug("%s health heartbeat failed: %s", bot, exc)

    write_bot_health(root, bot, extra=extra_provider() if extra_provider else None)
    threading.Thread(
        target=_loop,
        name=f"{bot}-health",
        daemon=True,
    ).start()
    return stop
