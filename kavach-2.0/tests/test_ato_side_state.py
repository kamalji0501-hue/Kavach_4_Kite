"""Per-side ATO halt flags."""

from __future__ import annotations

from core.ato_side_state import clear_all_side_halts, halt_side, is_side_halted, pause_all_ato


class _FakeState:
    def __init__(self) -> None:
        self._data: dict = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value, save=False):
        del save
        self._data[key] = value

    def save(self):
        pass


def test_halt_side_blocks_only_that_side():
    state = _FakeState()
    halt_side(state, "CE", reason="batman_qty_drift")
    assert is_side_halted(state, "CE") is True
    assert is_side_halted(state, "PE") is False


def test_global_algo_pause_halts_both():
    state = _FakeState()
    state.set("algo.paused", True)
    assert is_side_halted(state, "CE") is True
    assert is_side_halted(state, "PE") is True


def test_clear_all_side_halts():
    state = _FakeState()
    halt_side(state, "CE", reason="test")
    halt_side(state, "PE", reason="test")
    clear_all_side_halts(state)
    assert is_side_halted(state, "CE") is False
    assert is_side_halted(state, "PE") is False


def test_pause_all_ato():
    state = _FakeState()
    pause_all_ato(state, reason="position_book_unreadable")
    assert state.get("algo.paused") is True
    assert state.get("algo.pause_reason") == "position_book_unreadable"
    assert is_side_halted(state, "CE") is True


def test_clear_resumable_side_halts():
    from core.ato_side_state import clear_resumable_side_halts

    state = _FakeState()
    halt_side(state, "CE", reason="manual_protect_full_exit")
    halt_side(state, "PE", reason="batman_qty_drift")
    cleared = clear_resumable_side_halts(state)
    assert cleared == ["CE"]
    assert is_side_halted(state, "CE") is False
    assert is_side_halted(state, "PE") is True
