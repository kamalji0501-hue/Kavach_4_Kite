"""Tests for DRISHTI UAT Market Replay (tick log → shared cache)."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.nifty_ltp_uat_replay import (
    NiftyLtpUatReplayConfig,
    REPLAY_SPEED_FAST,
    REPLAY_SPEED_REALTIME,
    REPLAY_SPEED_ULTRA,
    ReplayTick,
    day_from_tick_log_path,
    is_drishti_uat_replay_window,
    load_ticks_from_log,
    load_uat_replay_config_from_params,
    parse_tick_log_line,
    replay_delay_seconds,
    resolve_replay_source_file,
)

_IST = ZoneInfo("Asia/Kolkata")


def test_parse_tick_log_line() -> None:
    tick = parse_tick_log_line("09:15:00.000 | 25100.00", day=date(2026, 7, 16))
    assert tick is not None
    assert tick.ltp == 25100.0
    assert tick.stored_at.hour == 9
    assert tick.stored_at.minute == 15


def test_parse_tick_log_line_with_event_suffix() -> None:
    tick = parse_tick_log_line("10:51:28.552 | 24147.60 | tick", day=date(2026, 7, 16))
    assert tick is not None
    assert tick.ltp == 24147.60


def test_day_from_tick_log_path() -> None:
    assert day_from_tick_log_path(Path("ws_ltp_20260716.log")) == date(2026, 7, 16)
    assert day_from_tick_log_path(Path("rest_ltp_20260715.log")) == date(2026, 7, 15)
    assert day_from_tick_log_path(Path("other.log")) is None


def test_load_ticks_from_log(tmp_path: Path) -> None:
    path = tmp_path / "ws_ltp_20260716.log"
    path.write_text(
        "09:15:00.000 | 25100.00\n"
        "09:15:01.000 | 25101.00\n"
        "09:15:02.000 | 25099.00\n"
        "bad line\n",
        encoding="utf-8",
    )
    ticks = load_ticks_from_log(path)
    assert [t.ltp for t in ticks] == [25100.0, 25101.0, 25099.0]


def test_replay_delay_speeds() -> None:
    day = date(2026, 7, 16)
    a = ReplayTick(datetime(2026, 7, 16, 9, 15, 0, tzinfo=_IST), 25100.0)
    b = ReplayTick(datetime(2026, 7, 16, 9, 15, 1, tzinfo=_IST), 25101.0)
    assert replay_delay_seconds(None, a, speed=REPLAY_SPEED_REALTIME) == 0.0
    assert replay_delay_seconds(a, b, speed=REPLAY_SPEED_REALTIME) == pytest.approx(1.0)
    assert replay_delay_seconds(a, b, speed=REPLAY_SPEED_FAST) == pytest.approx(1.0 / 3.0)
    assert replay_delay_seconds(a, b, speed=REPLAY_SPEED_ULTRA) == 0.0


def test_uat_window_overnight() -> None:
    cfg = NiftyLtpUatReplayConfig(
        window_start=time(15, 31),
        window_end=time(8, 55),
    )
    # After market close
    evening = datetime(2026, 7, 16, 16, 0, tzinfo=_IST)
    assert is_drishti_uat_replay_window(evening, config=cfg) is True
    # Before morning cutoff
    early = datetime(2026, 7, 17, 8, 0, tzinfo=_IST)
    assert is_drishti_uat_replay_window(early, config=cfg) is True
    # After morning cutoff, before NSE open
    buffer = datetime(2026, 7, 17, 9, 0, tzinfo=_IST)
    assert is_drishti_uat_replay_window(buffer, config=cfg) is False
    # During NSE session
    session = datetime(2026, 7, 16, 10, 0, tzinfo=_IST)
    assert is_drishti_uat_replay_window(session, config=cfg) is False


def test_resolve_prefers_websocket_log(tmp_path: Path) -> None:
    ws_dir = tmp_path / "2026-07" / "2026-07-16" / "drishti" / "logs" / "nifty_websocket_ltp"
    rest_dir = tmp_path / "2026-07" / "2026-07-16" / "drishti" / "logs" / "nifty_rest_ltp"
    ws_dir.mkdir(parents=True)
    rest_dir.mkdir(parents=True)
    ws = ws_dir / "ws_ltp_20260716.log"
    rest = rest_dir / "rest_ltp_20260716.log"
    lines = "\n".join(f"09:15:{i:02d}.000 | 25000.{i:02d}" for i in range(15)) + "\n"
    ws.write_text(lines, encoding="utf-8")
    rest.write_text(lines, encoding="utf-8")

    cfg = NiftyLtpUatReplayConfig(min_ticks=10, prefer_websocket_logs=True)
    chosen = resolve_replay_source_file(logs_root=tmp_path, config=cfg)
    assert chosen == ws


def test_load_config_from_params_defaults_fast() -> None:
    cfg = load_uat_replay_config_from_params({})
    assert cfg.replay_speed == REPLAY_SPEED_FAST
    assert cfg.enabled is True
    assert cfg.force_uat_mode is False
    assert cfg.window_start == time(15, 31)
    assert cfg.window_end == time(8, 55)

    cfg2 = load_uat_replay_config_from_params(
        {
            "uat_market_replay": {
                "enabled": True,
                "force_uat_mode": True,
                "replay_speed": "ultra",
                "window_start": "15:31",
                "window_end": "08:55",
            }
        }
    )
    assert cfg2.replay_speed == REPLAY_SPEED_ULTRA
    assert cfg2.force_uat_mode is True


def test_replay_progress_and_time_mapping() -> None:
    from core.nifty_ltp_uat_replay import (
        NiftyLtpUatReplayConfig,
        NiftyLtpUatReplayService,
        ReplayTick,
        format_clock_ampm,
        format_market_offset,
        format_uat_time_block,
    )

    day = date(2026, 7, 16)
    ticks = [
        ReplayTick(datetime(2026, 7, 16, 9, 47, 12, tzinfo=_IST), 24865.0),
        ReplayTick(datetime(2026, 7, 16, 9, 47, 13, tzinfo=_IST), 24866.0),
    ]
    svc = NiftyLtpUatReplayService(
        config=NiftyLtpUatReplayConfig(replay_speed=REPLAY_SPEED_FAST),
        source_file=Path("ws_ltp_20260716.log"),
        ticks=ticks,
        cache_path=Path("/tmp/unused_uat_cache.json"),
    )
    svc._last_emitted_tick = ticks[0]
    svc._last_emitted_wall = datetime(2026, 7, 16, 20, 42, 18, tzinfo=_IST)
    svc._tick_index = 1
    prog = svc.progress_snapshot(now=svc._last_emitted_wall)
    assert prog is not None
    assert prog.ltp == 24865.0
    assert prog.replay_market_time == ticks[0].stored_at
    assert prog.progress_percent == pytest.approx(50.0)
    assert prog.speed_multiplier == "3x"
    assert "09:47:12 AM" in format_clock_ampm(prog.replay_market_time) or "9:47:12 AM" in format_clock_ampm(
        prog.replay_market_time
    )
    assert "+10h" in format_market_offset(prog.market_offset_seconds)
    block = format_uat_time_block(prog)
    assert "Replay Market Time:" in block
    assert "Replay Progress:" in block
    assert "3x" in block


def test_speed_multiplier_labels() -> None:
    assert NiftyLtpUatReplayConfig(replay_speed=REPLAY_SPEED_REALTIME).speed_multiplier_label() == "1x"
    assert NiftyLtpUatReplayConfig(replay_speed=REPLAY_SPEED_FAST).speed_multiplier_label() == "3x"
    assert NiftyLtpUatReplayConfig(replay_speed=REPLAY_SPEED_ULTRA).speed_multiplier_label() == "max"


@pytest.mark.asyncio
async def test_replay_service_writes_shared_cache(tmp_path: Path, monkeypatch) -> None:
    from core.nifty_ltp_feed import read_nifty_ltp_cache
    from core.nifty_ltp_uat_replay import NiftyLtpUatReplayService

    path = tmp_path / "ws_ltp_20260716.log"
    path.write_text(
        "09:15:00.000 | 25100.00\n09:15:01.000 | 25101.00\n09:15:02.000 | 25099.00\n",
        encoding="utf-8",
    )
    ticks = load_ticks_from_log(path)
    cache = tmp_path / "nifty_ltp_cache.json"
    cfg = NiftyLtpUatReplayConfig(
        replay_speed=REPLAY_SPEED_ULTRA,
        loop=False,
        window_start=time(0, 0),
        window_end=time(23, 59),
    )
    monkeypatch.setattr(
        "core.nifty_ltp_uat_replay.is_nse_market_session",
        lambda *a, **k: False,
    )
    service = NiftyLtpUatReplayService(
        config=cfg,
        source_file=path,
        ticks=ticks,
        cache_path=cache,
    )
    service._running = True
    await service.run()
    snap = read_nifty_ltp_cache(cache)
    assert snap is not None
    assert snap.ltp == 25099.0
    assert snap.source == "uat_replay"
    assert snap.feed_healthy is True
    prog = service.progress_snapshot()
    assert prog is not None
    assert prog.ltp == 25099.0
    assert prog.replay_market_time.hour == 9
    assert prog.replay_market_time.minute == 15
    assert prog.replay_market_time.second == 2
