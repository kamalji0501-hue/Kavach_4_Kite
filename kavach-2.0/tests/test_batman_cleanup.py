"""Tests for core.batman_cleanup."""

from __future__ import annotations

from pathlib import Path

from core.batman_cleanup import verify_batman_cleanup


def test_verify_batman_cleanup_no_active_files(tmp_path: Path):
    all_ok, checks = verify_batman_cleanup(deploy_dir=tmp_path, state_get=None)
    assert all_ok is True
    assert checks[0][1] is True


def test_verify_batman_cleanup_with_state():
    state = {
        "deployment.confirmed": False,
        "deployment.file": None,
        "positions.pe_buy": None,
        "positions.pe_sell": None,
        "positions.ce_buy": None,
        "positions.ce_sell": None,
        "ato.ce_triggered": False,
        "ato.pe_triggered": False,
        "deployment.batman_complete": True,
    }

    def getter(key: str):
        return state.get(key)

    all_ok, checks = verify_batman_cleanup(deploy_dir=Path("/nonexistent"), state_get=getter)
    assert all_ok is True
    assert len(checks) == 6
