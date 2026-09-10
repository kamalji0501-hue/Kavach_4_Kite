"""flatten_now does not require a PnL level."""

from __future__ import annotations

from unittest.mock import MagicMock

from core import pnl_exit_guard as peg


class _State:
    def __init__(self) -> None:
        self._d: dict = {}

    def get(self, k, default=None):
        return self._d.get(k, default)

    def set(self, k, v, save=True):
        self._d[k] = v

    def save(self) -> None:
        pass


def test_flatten_now_calls_sequenced_flatten_without_pnl_level(monkeypatch) -> None:
    broker = MagicMock()
    state = _State()
    called: dict = {}

    def fake_flatten(b):
        called["broker"] = b
        return {
            "orders_placed": 2,
            "order_ids": ["1", "2"],
            "legs_seen": 2,
            "legs_left": 0,
            "left_symbols": [],
        }

    monkeypatch.setattr(peg, "sequenced_flatten", fake_flatten)
    monkeypatch.setattr(peg, "current_day_pnl", lambda: None)
    monkeypatch.setattr(peg, "_pause_ato", lambda s: called.setdefault("paused", True))
    monkeypatch.setattr(peg, "_notify", lambda *a, **k: called.setdefault("notified", True))

    out = peg.flatten_now(broker=broker, state=state, reason="manual_exit")
    assert out["ok"] is True
    assert out["reason"] == "manual_exit"
    assert called["broker"] is broker
    assert called.get("paused") is True
    assert called.get("notified") is True
    assert state.get(peg.KEY_SAFE_ON) is False
    assert state.get(peg.KEY_TP_ON) is False
    assert state.get(peg.KEY_SAFE_LEVEL) is None
    assert state.get(peg.KEY_TP_LEVEL) is None
    assert state.get(peg.KEY_FIRING) is False
    assert state.get(peg.KEY_LAST_REASON) == "manual_exit"
    assert "level" not in str(out.get("text") or "") or out.get("level") is None


def test_check_and_maybe_fire_still_requires_level(monkeypatch) -> None:
    broker = MagicMock()
    state = _State()
    state.set(peg.KEY_SAFE_ON, True)
    state.set(peg.KEY_SAFE_LEVEL, None)
    monkeypatch.setattr(peg, "current_day_pnl", lambda: 100.0)
    called = {"n": 0}

    def boom(**kwargs):
        called["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(peg, "flatten_now", boom)
    assert peg.check_and_maybe_fire(broker=broker, state=state) is None
    assert called["n"] == 0


def test_check_and_maybe_fire_delegates_to_flatten_now(monkeypatch) -> None:
    broker = MagicMock()
    state = _State()
    state.set(peg.KEY_SAFE_ON, True)
    state.set(peg.KEY_SAFE_LEVEL, -500.0)
    monkeypatch.setattr(peg, "current_day_pnl", lambda: -600.0)
    captured: dict = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "reason": kwargs["reason"]}

    monkeypatch.setattr(peg, "flatten_now", fake)
    out = peg.check_and_maybe_fire(broker=broker, state=state)
    assert out and out["ok"] is True
    assert captured["reason"] == "safe_exit"
    assert captured["level"] == -500.0
    assert captured["broker"] is broker
