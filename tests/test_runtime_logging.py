from __future__ import annotations

import logging
from datetime import datetime

from core import runtime_logging as rl
from core.runtime_logging import _window_name, set_logging_robot


def test_window_name_regular_hour() -> None:
    ts = datetime(2026, 5, 16, 10, 14, 0)
    assert _window_name(ts).endswith("_1000_1100")


def test_window_name_market_close_split_early() -> None:
    ts = datetime(2026, 5, 16, 15, 12, 0)
    assert _window_name(ts).endswith("_1500_1530")


def test_window_name_market_close_split_post() -> None:
    ts = datetime(2026, 5, 16, 15, 44, 0)
    assert _window_name(ts).endswith("_post_1530_1600")


def test_window_name_post_market_hourly() -> None:
    ts = datetime(2026, 5, 16, 17, 4, 0)
    assert _window_name(ts).endswith("_post_1700_1800")


def test_window_name_pre_market_hourly_post_class() -> None:
    ts = datetime(2026, 5, 16, 8, 40, 0)
    assert _window_name(ts).endswith("_post_0800_0900")


def _record(*, name: str, msg: str, created_ts: datetime) -> logging.LogRecord:
    from zoneinfo import ZoneInfo

    rec = logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    # Pin to IST so Chromebook/UTC hosts match Windows-IST window names.
    if created_ts.tzinfo is None:
        created_ts = created_ts.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    rec.created = created_ts.timestamp()
    return rec


def test_runtime_handler_writes_main_and_robot_logs(tmp_path) -> None:
    set_logging_robot("drishti")
    handler = rl.WindowedRuntimeFileHandler(tmp_path)
    ts = datetime(2026, 5, 16, 10, 5, 0, 123000)
    rec = _record(name="batman.drishti", msg="Token check passed", created_ts=ts)

    handler.emit(rec)

    day_root = tmp_path / "2026-05" / "2026-05-16"
    main_file = day_root / "logs" / "runtime_20260516_1000_1100.log"
    robot_file = day_root / "drishti" / "logs" / "drishti_20260516_1000_1100.log"
    robot_all = day_root / "drishti" / "logs" / "all.log"
    main_all = day_root / "logs" / "all.log"

    assert main_file.exists()
    assert robot_file.exists()
    assert robot_all.exists()
    assert main_all.exists()
    assert not (day_root / "logs" / "drishti_20260516_1000_1100.log").exists()

    main_text = main_file.read_text(encoding="utf-8")
    robot_all_text = robot_all.read_text(encoding="utf-8")
    assert "DRISHTI" in main_text
    assert "Token check passed" in robot_all_text


def test_runtime_handler_writes_error_rollups_in_robot_folder(tmp_path) -> None:
    set_logging_robot("kavach")
    handler = rl.WindowedRuntimeFileHandler(tmp_path)
    ts = datetime(2026, 5, 16, 10, 5, 0, 123000)
    rec = _record(name="batman.kavach", msg="ATO LTP stale", created_ts=ts)
    rec.levelno = logging.ERROR
    rec.levelname = "ERROR"

    handler.emit(rec)

    day_root = tmp_path / "2026-05" / "2026-05-16"
    assert (day_root / "logs" / "runtime_20260516_1000_1100_errors.log").exists()
    assert (day_root / "kavach" / "errors" / "all_errors.log").exists()

    err_text = (day_root / "kavach" / "errors" / "all_errors.log").read_text(
        encoding="utf-8"
    )
    assert "ATO LTP stale" in err_text
    assert "ERROR" in err_text


def test_runtime_handler_skips_error_files_for_info(tmp_path) -> None:
    set_logging_robot("jagran")
    handler = rl.WindowedRuntimeFileHandler(tmp_path)
    ts = datetime(2026, 5, 16, 10, 5, 0, 123000)
    rec = _record(name="batman.jagran", msg="heartbeat ok", created_ts=ts)

    handler.emit(rec)

    day_root = tmp_path / "2026-05" / "2026-05-16"
    assert not (day_root / "jagran" / "errors" / "all_errors.log").exists()
    assert not (day_root / "logs" / "runtime_20260516_1000_1100_errors.log").exists()


def test_runtime_handler_rolls_to_close_and_post_market_windows(tmp_path) -> None:
    set_logging_robot("kavach")
    handler = rl.WindowedRuntimeFileHandler(tmp_path)

    rec_early = _record(
        name="batman.kavach",
        msg="pre-close check",
        created_ts=datetime(2026, 5, 16, 15, 20, 0, 111000),
    )
    rec_post = _record(
        name="batman.kavach",
        msg="post-close check",
        created_ts=datetime(2026, 5, 16, 15, 45, 0, 222000),
    )

    handler.emit(rec_early)
    handler.emit(rec_post)

    day_root = tmp_path / "2026-05" / "2026-05-16" / "logs"
    assert (day_root / "runtime_20260516_1500_1530.log").exists()
    assert (day_root / "runtime_20260516_post_1530_1600.log").exists()
