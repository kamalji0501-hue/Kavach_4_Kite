#!/usr/bin/env python3
"""Tests for structured instance locks."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.instance_lock import (
    InstanceLockRecord,
    heal_stale_lock,
    is_stale_lock,
    lock_pid,
    read_lock,
    remove_lock_files,
    write_lock,
)


def test_write_read_json_lock(tmp_path: Path) -> None:
    lock = tmp_path / "kavach.lock"
    record = InstanceLockRecord(
        pid=12345,
        runner="run_kavach.py",
        started_at="2026-06-12T10:00:00+05:30",
        hostname="testhost",
    )
    write_lock(lock, record)
    parsed = read_lock(lock)
    assert parsed is not None
    assert parsed.pid == 12345
    assert parsed.runner == "run_kavach.py"


def test_read_legacy_plain_pid(tmp_path: Path) -> None:
    lock = tmp_path / "drishti.lock"
    lock.write_text("99999", encoding="utf-8")
    record = read_lock(lock)
    assert record is not None
    assert record.pid == 99999
    assert record.version == 0


def test_lock_pid_helper(tmp_path: Path) -> None:
    lock = tmp_path / "jagran.lock"
    lock.write_text("42", encoding="utf-8")
    assert lock_pid(lock) == 42


def test_stale_when_dead_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = tmp_path / "kavach.lock"
    write_lock(lock, InstanceLockRecord.current("run_kavach.py"))
    monkeypatch.setattr("core.instance_lock.process_alive", lambda _pid: False)
    assert is_stale_lock(lock, "run_kavach.py") is True
    assert heal_stale_lock(lock, "run_kavach.py") is True
    assert not lock.exists()


def test_stale_when_pid_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = tmp_path / "kavach.lock"
    write_lock(
        lock,
        InstanceLockRecord(
            pid=15892,
            runner="run_kavach.py",
            started_at="2026-06-12T09:00:00+05:30",
            hostname="pc",
        ),
    )
    monkeypatch.setattr("core.instance_lock.process_alive", lambda _pid: True)
    monkeypatch.setattr("core.instance_lock.pid_owns_runner", lambda _pid, _r: False)
    assert is_stale_lock(lock, "run_kavach.py") is True
    assert remove_lock_files(lock) is True
