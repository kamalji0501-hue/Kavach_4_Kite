"""Tests for core.bot_logging."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.bot_logging import (
    bot_all_errors_path,
    bot_all_log_path,
    bot_nifty_ltp_log_dir,
    configure_bot_logging,
    main_all_log_path,
    runtime_day_dir,
)

_IST = ZoneInfo("Asia/Kolkata")


def test_runtime_paths_under_single_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ts = datetime(2026, 6, 2, 10, 0, 0, tzinfo=_IST)
    runtime_root = tmp_path / "logs" / "runtime"
    monkeypatch.setattr(
        "core.batman_mode.log_runtime_root",
        lambda _root=None: runtime_root,
    )
    assert runtime_day_dir(tmp_path, ts) == runtime_root / "2026-06" / "2026-06-02"
    day = runtime_root / "2026-06" / "2026-06-02"
    assert bot_all_log_path(tmp_path, "kavach", ts=ts) == day / "kavach" / "logs" / "all.log"
    assert bot_nifty_ltp_log_dir(tmp_path, ts=ts) == day / "drishti" / "logs" / "nifty_ltp"
    assert main_all_log_path(tmp_path, ts=ts) == day / "logs" / "all.log"


def test_configure_bot_logging_writes_runtime_all_log(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "settings.json").write_text(
        '{"logging": {"enabled": true, "level": "INFO", "root_dir": "logs/runtime"}}',
        encoding="utf-8",
    )
    path = configure_bot_logging(workspace_root=tmp_path, bot_name="jagran")
    logging.getLogger("batman.jagran.test").info("bootstrap ok")
    logging.getLogger("batman.jagran.test").error("bootstrap fail")
    assert path.name == "all.log"
    assert path.exists()
    assert "bootstrap ok" in path.read_text(encoding="utf-8")
    err_path = bot_all_errors_path(tmp_path, "jagran")
    assert err_path.exists()
    assert "bootstrap fail" in err_path.read_text(encoding="utf-8")
    assert not (tmp_path / "logs" / "bots").exists()
