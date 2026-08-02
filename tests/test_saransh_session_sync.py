"""SARANSH session sync + always-restart on Complete (OQ-P1-21)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from core.saransh_paths import ato_cycle_feed_path, session_manifest_path
from core.saransh_session_sync import (
    restart_saransh,
    saransh_session_complete,
    saransh_session_reset_feeds_only,
)


def _uat_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("BATMAN_MODE", "uat")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "batman_mode.json").write_text(
        '{"mode": "uat", "modes": {"uat": {"data_root": "data/uat"}}}',
        encoding="utf-8",
    )
    (tmp_path / "telegram" / "bots" / "saransh").mkdir(parents=True)
    (tmp_path / "telegram" / "bots" / "saransh" / "params.json").write_text(
        '{"enabled": true}',
        encoding="utf-8",
    )
    (tmp_path / "telegram" / "bots" / "saransh" / "token.env").write_text(
        "SARANSH_BOT_TOKEN=123:abc\nSARANSH_CHAT_ID=-1\n",
        encoding="utf-8",
    )
    import sys

    if sys.platform == "win32":
        (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
        py = tmp_path / ".venv" / "Scripts" / "python.exe"
    else:
        (tmp_path / ".venv" / "bin").mkdir(parents=True)
        py = tmp_path / ".venv" / "bin" / "python"
    py.write_text("", encoding="utf-8")
    py.chmod(0o755)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "stop_saransh.py").write_text("# stub", encoding="utf-8")
    (tmp_path / "run_saransh.py").write_text("# stub", encoding="utf-8")
    bat_dir = tmp_path / "Execution" / "Start Bots"
    bat_dir.mkdir(parents=True)
    (bat_dir / "start Saransh.bat").write_text("@echo off", encoding="utf-8")
    (bat_dir / "start Saransh.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    return tmp_path


def test_reset_feeds_only_deletes_jsonl(tmp_path: Path, monkeypatch) -> None:
    root = _uat_root(tmp_path, monkeypatch)
    feed = ato_cycle_feed_path(root)
    feed.parent.mkdir(parents=True, exist_ok=True)
    feed.write_text('{"event":"x"}\n', encoding="utf-8")
    saransh_session_reset_feeds_only(root=root)
    assert not feed.exists()


def test_restart_always_stop_then_start(tmp_path: Path, monkeypatch) -> None:
    root = _uat_root(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd) if isinstance(cmd, list) else [str(cmd)])
        return MagicMock(returncode=0)

    def fake_popen(cmd, **kwargs):
        calls.append(list(cmd) if isinstance(cmd, list) else [str(cmd)])
        return MagicMock()

    monkeypatch.setattr("core.saransh_session_sync.subprocess.run", fake_run)
    monkeypatch.setattr("core.saransh_session_sync.subprocess.Popen", fake_popen)
    result = restart_saransh(root=root, reason="batman_complete")
    assert result.get("ok") is True
    assert any("stop_saransh.py" in " ".join(c) for c in calls)
    joined = " ".join(" ".join(c) for c in calls)
    assert "start Saransh.sh" in joined or "start Saransh.bat" in joined


def test_batman_complete_writes_manifest(tmp_path: Path, monkeypatch) -> None:
    root = _uat_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "core.saransh_session_sync.restart_saransh",
        lambda **_: {"ok": True, "reason": "batman_complete"},
    )
    out = saransh_session_complete(root=root)
    manifest_path = session_manifest_path(root)
    assert manifest_path.is_file()
    assert out["manifest"]["status"] == "completed"
    assert out["manifest"]["restart_reason"] == "batman_complete"


def test_restart_skipped_without_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BATMAN_MODE", "uat")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "batman_mode.json").write_text('{"mode": "uat"}', encoding="utf-8")
    result = restart_saransh(root=tmp_path)
    assert result.get("skipped") is True
