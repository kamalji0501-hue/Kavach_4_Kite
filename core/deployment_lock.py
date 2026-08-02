"""Global deployment session lock — Register, Batman Complete, Emergency Exit, ATO."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from collections.abc import Generator

_LOCK = threading.RLock()
_OWNER: str | None = None
_ACQUIRED_AT: float | None = None


class DeploymentLockBusy(Exception):
    """Another deployment-critical operation holds the lock."""


def lock_owner() -> str | None:
    return _OWNER


def is_locked() -> bool:
    return _LOCK.locked()


@contextmanager
def deployment_session(
    owner: str,
    *,
    timeout: float = 60.0,
    blocking: bool = True,
) -> Generator[None, None, None]:
    """Serialize deployment mutations and ATO order placement."""
    global _OWNER, _ACQUIRED_AT
    acquired = False
    if blocking:
        acquired = _LOCK.acquire(timeout=max(0.0, timeout))
    else:
        acquired = _LOCK.acquire(blocking=False)
    if not acquired:
        raise DeploymentLockBusy(
            f"deployment lock held by {_OWNER or 'unknown'} — {owner} cannot proceed"
        )
    _OWNER = owner
    _ACQUIRED_AT = time.monotonic()
    try:
        yield
    finally:
        _OWNER = None
        _ACQUIRED_AT = None
        _LOCK.release()


def try_deployment_session(owner: str) -> bool:
    """Non-blocking acquire; returns True if lock taken (must call release_deployment_session)."""
    global _OWNER, _ACQUIRED_AT
    if not _LOCK.acquire(blocking=False):
        return False
    _OWNER = owner
    _ACQUIRED_AT = time.monotonic()
    return True


def release_deployment_session() -> None:
    global _OWNER, _ACQUIRED_AT
    _OWNER = None
    _ACQUIRED_AT = None
    _LOCK.release()
