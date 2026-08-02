"""Tests for Phase 1 startup gates."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.bot_process_status import BotProcessStatus, BotRunState
from core.startup_gates import ltp_gate_skip_reason, nifty_cache_age_seconds, wait_bot_running

_IST = ZoneInfo("Asia/Kolkata")


def test_nifty_cache_age_seconds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rr = tmp_path / "Batman-Runtime"
    monkeypatch.setenv("BATMAN_RUNTIME_ROOT", str(rr))
    cache = rr / "data" / "shared" / "nifty_ltp_cache.json"
    cache.parent.mkdir(parents=True)
    now = datetime.now(_IST)
    cache.write_text(
        json.dumps({"ltp": 23300.0, "updated_at": now.isoformat()}),
        encoding="utf-8",
    )
    age = nifty_cache_age_seconds(root=tmp_path)
    assert age is not None
    assert age < 5.0


def test_ltp_gate_skip_reason_post_market() -> None:
    after_close = datetime(2026, 6, 25, 16, 0, tzinfo=_IST)
    assert ltp_gate_skip_reason(now=after_close) == "post_market"


def test_ltp_gate_skip_reason_live_session() -> None:
    during_session = datetime(2026, 6, 25, 10, 30, tzinfo=_IST)
    assert ltp_gate_skip_reason(now=during_session) is None


def test_wait_bot_running_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_classify(robot: str, *, root=None):
        calls["n"] += 1
        if calls["n"] >= 2:
            return BotProcessStatus(
                robot=robot,
                runner_marker=f"run_{robot}.py",
                lock_path=Path(f"data/{robot}.lock"),
                pids=(1,),
                lock_pid=1,
                state=BotRunState.RUNNING,
                warnings=(),
            )
        return BotProcessStatus(
            robot=robot,
            runner_marker=f"run_{robot}.py",
            lock_path=Path(f"data/{robot}.lock"),
            pids=(),
            lock_pid=None,
            state=BotRunState.STOPPED,
            warnings=(),
        )

    monkeypatch.setattr("core.startup_gates.classify_bot", fake_classify)
    assert wait_bot_running("drishti", timeout_seconds=5.0, poll_seconds=0.01) is True
