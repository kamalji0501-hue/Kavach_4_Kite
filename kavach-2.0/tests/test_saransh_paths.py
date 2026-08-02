"""SARANSH mode-aware path helpers."""

from __future__ import annotations

from pathlib import Path

from core.batman_mode import saransh_lock_path
from core.saransh_paths import (
    ato_cycle_feed_path,
    saransh_analytics_dir,
    session_manifest_path,
)


def test_saransh_paths_under_mode_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BATMAN_RUNTIME_ROOT", raising=False)
    monkeypatch.setenv("BATMAN_MODE", "uat")
    rr = tmp_path / "Batman-Runtime"
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "batman_mode.json").write_text(
        f'{{"mode": "uat", "runtime_root": "{str(rr).replace(chr(92), "/")}"}}',
        encoding="utf-8",
    )
    assert saransh_analytics_dir(tmp_path) == rr / "data" / "uat" / "analytics" / "saransh"
    assert ato_cycle_feed_path(tmp_path) == (
        rr / "data" / "uat" / "analytics" / "ato" / "ato_cycle_feed.jsonl"
    )
    assert session_manifest_path(tmp_path) == (
        rr / "data" / "uat" / "analytics" / "session_manifest.json"
    )
    assert saransh_lock_path(tmp_path) == rr / "data" / "uat" / "saransh.lock"
