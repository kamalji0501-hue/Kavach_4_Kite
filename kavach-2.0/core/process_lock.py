"""Cross-process file locking for Windows (Phase 1 laptop bots)."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def exclusive_file_lock(
    path: Path,
    *,
    timeout: float = 10.0,
    poll: float = 0.05,
    retries: int = 3,
):
    """Acquire an exclusive lock with short retries on contention."""
    last_exc: TimeoutError | None = None
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            with _exclusive_file_lock_once(path, timeout=timeout, poll=poll) as lock_path:
                yield lock_path
            return
        except TimeoutError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(min(0.25 * (attempt + 1), 1.0))
    assert last_exc is not None
    raise last_exc


@contextlib.contextmanager
def _exclusive_file_lock_once(path: Path, *, timeout: float = 10.0, poll: float = 0.05):
    """Acquire an exclusive lock file adjacent to *path*.

    Uses ``O_EXCL`` create — safe for DRISHTI/KAVACH/JAGRAN single-writer
    coordination on ``batman_state.json`` and bot PID locks.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire lock: {lock_path}") from None
            time.sleep(poll)
    try:
        yield lock_path
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Lock release failed for %s: %s", lock_path, exc)
