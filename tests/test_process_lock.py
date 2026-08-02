"""Tests for cross-process file lock retries."""

from __future__ import annotations

import threading
from pathlib import Path

from core.process_lock import exclusive_file_lock


def test_exclusive_file_lock_retries_on_contention(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_text("{}", encoding="utf-8")
    holder = threading.Event()
    release = threading.Event()
    acquired = {"n": 0}

    def hold_lock() -> None:
        with exclusive_file_lock(target, timeout=2.0, retries=1):
            acquired["n"] += 1
            holder.set()
            release.wait(timeout=3.0)

    t = threading.Thread(target=hold_lock)
    t.start()
    assert holder.wait(timeout=2.0)
    with exclusive_file_lock(target, timeout=2.0, retries=3):
        pass
    release.set()
    t.join(timeout=3.0)
    assert acquired["n"] == 1
