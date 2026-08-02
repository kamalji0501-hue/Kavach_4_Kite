"""Tests for global deployment session lock."""

from __future__ import annotations

import threading
import time

from core.deployment_lock import DeploymentLockBusy, deployment_session, lock_owner


def test_deployment_session_serializes() -> None:
    order: list[str] = []

    def worker(name: str) -> None:
        with deployment_session(name, timeout=2.0):
            order.append(f"{name}-start")
            time.sleep(0.05)
            order.append(f"{name}-end")

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert order.index("a-start") < order.index("a-end")
    assert order.index("b-start") < order.index("b-end")
    assert lock_owner() is None


def test_deployment_session_busy_raises() -> None:
    errors: list[Exception] = []

    def contender() -> None:
        try:
            with deployment_session("other", timeout=0.2, blocking=True):
                pass
        except DeploymentLockBusy as exc:
            errors.append(exc)

    with deployment_session("holder", timeout=1.0):
        t = threading.Thread(target=contender)
        t.start()
        t.join(timeout=2.0)

    assert len(errors) == 1
