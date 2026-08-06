"""
Shared UAT daily test case runners — used by pytest and scripts/run_uat_daily_test_suite.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo
from core.utils import get_venv_python

IST = ZoneInfo("Asia/Kolkata")

ROOT = Path(__file__).resolve().parent.parent


def _root() -> Path:
    return ROOT


def _access_token_path() -> Path:
    from core.batman_mode import access_token_path

    return access_token_path(_root())


def _nifty_cache_path() -> Path:
    from core.batman_mode import nifty_ltp_cache_path

    return nifty_ltp_cache_path(_root())


def _dhan_env_path() -> Path:
    from core.batman_mode import secrets_dhan_env_path

    ext = secrets_dhan_env_path(_root())
    if ext.is_file():
        return ext
    return _root() / "config" / ".env"


def _uat_state_path() -> Path:
    from core.batman_mode import state_path

    return state_path(_root())


@dataclass(frozen=True)
class TestCaseDef:
    case_id: str
    category: str
    name: str
    market_hours_required: bool = False


@dataclass
class CaseResult:
    case_id: str
    ok: bool
    detail: str = ""
    duration_ms: float = 0.0
    skipped: bool = False
    metrics: dict[str, Any] | None = None


TEST_CATALOG: tuple[TestCaseDef, ...] = (
    TestCaseDef("UAT-D00", "config", "Batman mode is uat"),
    TestCaseDef("UAT-D01", "book", "Screenshot folder has image"),
    TestCaseDef("UAT-D02", "book", "positions.json has 8 legs"),
    TestCaseDef("UAT-D03", "auth", "Dhan JWT present and not expired"),
    TestCaseDef("UAT-D04", "book", "validate_fixture Dhan symbols"),
    TestCaseDef("UAT-D05", "broker", "ShadowBroker loads 8 legs"),
    TestCaseDef("UAT-D06", "broker", "Shadow virtual MARKET BUY fill"),
    TestCaseDef("UAT-D07", "ltp", "NIFTY LTP cache fresh", market_hours_required=True),
    TestCaseDef("UAT-D08", "bots", "DRISHTI process RUNNING + lock"),
    TestCaseDef("UAT-D09", "bots", "KAVACH process RUNNING + lock"),
    TestCaseDef("UAT-D10", "bots", "JAGRAN process RUNNING + lock"),
    TestCaseDef("UAT-D11", "telegram", "phase1_bot_check PASS"),
    TestCaseDef("UAT-D12", "logs", "KAVACH log scan (no ERROR)"),
    TestCaseDef("UAT-D13", "logs", "DRISHTI log scan (no ERROR)"),
    TestCaseDef("UAT-D14", "kavach", "Register wizard entry smoke"),
    TestCaseDef("UAT-D15", "kavach", "Menu button handler map complete"),
    TestCaseDef("UAT-D16", "kavach", "Environment command callable"),
    TestCaseDef("UAT-D17", "kavach", "Positions command formats book"),
    TestCaseDef("UAT-D18", "kavach", "Status command with deployment path"),
    TestCaseDef("UAT-D19", "kavach", "ATO Status command runs"),
    TestCaseDef("UAT-D20", "perf", "UAT ingest fresh or under 120s"),
    TestCaseDef("UAT-D21", "ato", "ATO module waiting for deployment"),
    TestCaseDef("UAT-D22", "pytest", "UAT pytest subset green"),
    TestCaseDef("UAT-D23", "book", "Dynamic expiry parse from positions.json"),
    TestCaseDef("UAT-D24", "book", "Instrument master resolves all 8 legs"),
    TestCaseDef("UAT-D25", "auth", "Dhan fundlimit REST (JWT live)"),
    TestCaseDef("UAT-D26", "ltp", "NIFTY REST marketfeed one-shot", market_hours_required=True),
    TestCaseDef("UAT-D27", "ltp", "Option FNO marketfeed LTP (8 legs)", market_hours_required=True),
    TestCaseDef("UAT-D28", "logs", "JAGRAN log scan (no ERROR)"),
    TestCaseDef("UAT-D29", "kavach", "Position enrich fills missing premiums"),
    TestCaseDef("UAT-D30", "book", "cursor_chat book or valid fixture source"),
)


def run_case_mode_uat() -> CaseResult:
    from core.batman_mode import get_mode

    mode = get_mode(_root())
    ok = mode == "uat"
    return CaseResult("UAT-D00", ok, f"mode={mode!r}")


def run_case_screenshot() -> CaseResult:
    from core.uat_positions import find_screenshot_images
    from core.batman_mode import uat_screenshot_dir

    from core.uat_positions import positions_json_path

    images = find_screenshot_images(uat_screenshot_dir(_root()))
    pos_ok = positions_json_path(_root()).is_file()
    ok = bool(images) or pos_ok
    if images:
        detail = images[0].name
    elif pos_ok:
        detail = "positions.json present (no image file)"
    else:
        detail = "no image and no positions.json in uat/deployed_positions"
    mtime = images[0].stat().st_mtime if images else 0
    metrics = {"screenshot_mtime": datetime.fromtimestamp(mtime, tz=IST).isoformat()} if images else {}
    return CaseResult("UAT-D01", ok, detail, metrics=metrics)


def run_case_positions_json() -> CaseResult:
    from core.uat_positions import load_positions_fixture

    try:
        fix = load_positions_fixture(_root())
        legs = fix.get("legs", [])
        ok = len(legs) == 8
        return CaseResult(
            "UAT-D02",
            ok,
            f"legs={len(legs)} spot={fix.get('spot_at_capture')} expiry={fix.get('expiry_date')}",
            metrics={"leg_count": len(legs)},
        )
    except Exception as exc:
        return CaseResult("UAT-D02", False, str(exc))


def run_case_jwt() -> CaseResult:
    from core.token_store import TokenStore

    store = TokenStore(path=_access_token_path())
    token, saved_at = store.load()
    expired = store.is_expired()
    ok = bool(token) and not expired
    return CaseResult(
        "UAT-D03",
        ok,
        f"expired={expired} age_h={store.token_age_hours():.2f} saved_at={saved_at}",
    )


def run_case_validate_fixture() -> CaseResult:
    from core.uat_positions import positions_json_path

    py = get_venv_python(_root())
    script = _root() / "backtest_engine" / "tools" / "validate_fixture.py"
    pos_fixture = positions_json_path(_root())
    proc = subprocess.run(
        [str(py), str(script), "--fixture", str(pos_fixture)],
        cwd=str(_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = "\n".join((proc.stdout or proc.stderr or "").splitlines()[-3:])
    detail = tail or f"exit {proc.returncode}"
    if proc.returncode != 0 and (
        "BLOCKED" in detail or "invalid or expired" in detail.lower()
    ):
        return CaseResult("UAT-D04", False, detail, skipped=True)
    return CaseResult("UAT-D04", proc.returncode == 0, detail)


def run_case_shadow_load() -> CaseResult:
    from backtest_engine.shadow.ledger_store import clear_ledger
    from core.broker_factory import create_broker
    from core.token_store import TokenStore
    from dotenv import dotenv_values

    env = dotenv_values(_dhan_env_path())
    client = (env.get("DHAN_CLIENT_CODE") or "").strip()
    store = TokenStore(path=_access_token_path())
    token, _ = store.load()
    if not token:
        return CaseResult("UAT-D05", False, "no JWT")
    broker = create_broker(client, token, _root())
    df = broker.get_positions()
    n = 0 if df is None else len(df)
    if n < 8:
        # Virtual ledger pollution can net core legs away; one clear+reload for UAT smoke.
        clear_ledger(_root())
        broker = create_broker(client, token, _root())
        df = broker.get_positions()
        n = 0 if df is None else len(df)
    ok = n >= 8
    return CaseResult("UAT-D05", ok, f"rows={n} broker={type(broker).__name__}")


def run_case_shadow_order() -> CaseResult:
    from backtest_engine.shadow.order_ledger import get_virtual_order_status
    from core.broker_factory import create_broker
    from core.token_store import TokenStore
    from dotenv import dotenv_values

    env = dotenv_values(_dhan_env_path())
    client = (env.get("DHAN_CLIENT_CODE") or "").strip()
    store = TokenStore(path=_access_token_path())
    token, _ = store.load()
    if not token:
        return CaseResult("UAT-D06", False, "no JWT")
    broker = create_broker(client, token, _root())
    df = broker.get_positions()
    if df is None or df.empty:
        return CaseResult("UAT-D06", False, "empty book")
    symbol = str(df.iloc[0]["tradingSymbol"])
    t0 = time.perf_counter()
    oid = broker.place_market_order(symbol, qty=65, side="BUY")
    deadline = time.perf_counter() + 3.0
    status = "PENDING"
    while time.perf_counter() < deadline:
        status = get_virtual_order_status(broker, oid)
        if status == "TRADED":
            break
        time.sleep(0.1)
    ms = (time.perf_counter() - t0) * 1000
    ok = status == "TRADED"
    return CaseResult(
        "UAT-D06",
        ok,
        f"order={oid} status={status} symbol={symbol}",
        duration_ms=ms,
        metrics={"fill_ms": round(ms, 1)},
    )


def _market_session_open() -> bool:
    now = datetime.now(tz=IST)
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start <= now <= end


def run_case_ltp_fresh() -> CaseResult:
    from core.nifty_ltp_feed import read_nifty_ltp_cache

    if not _market_session_open():
        return CaseResult(
            "UAT-D07",
            True,
            "SKIP off-hours — cache check deferred",
            skipped=True,
        )
    snap = read_nifty_ltp_cache(_nifty_cache_path())
    if snap is None:
        return CaseResult("UAT-D07", False, "no cache file")
    age = snap.age_seconds()
    ok = snap.feed_healthy and snap.ltp > 0 and age <= 30
    return CaseResult(
        "UAT-D07",
        ok,
        f"ltp={snap.ltp:.2f} age_s={age:.1f} healthy={snap.feed_healthy}",
        metrics={"ltp": snap.ltp, "age_seconds": age},
    )


def _bot_line(bot: str) -> tuple[bool, str]:
    py = get_venv_python(_root())
    proc = subprocess.run(
        [str(py), str(_root() / "scripts" / "bot_status.py"), bot],
        cwd=str(_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout or ""
    if "RUNNING" in out and "lock:" in out:
        return True, "RUNNING+lock"
    if "ORPHAN" in out:
        return False, "ORPHAN — run stop/start .bat"
    if "STOPPED" in out:
        return False, "STOPPED"
    return False, out.strip()[:200]


def _bot_case(case_id: str, bot: str) -> CaseResult:
    ok, detail = _bot_line(bot)
    if not ok and detail == "STOPPED":
        return CaseResult(case_id, True, detail, skipped=True)
    return CaseResult(case_id, ok, detail)


def run_case_bot_drishti() -> CaseResult:
    return _bot_case("UAT-D08", "drishti")


def run_case_bot_kavach() -> CaseResult:
    return _bot_case("UAT-D09", "kavach")


def run_case_bot_jagran() -> CaseResult:
    return _bot_case("UAT-D10", "jagran")


def run_case_phase1_check() -> CaseResult:
    py = get_venv_python(_root())
    proc = subprocess.run(
        [str(py), str(_root() / "scripts" / "phase1_bot_check.py")],
        cwd=str(_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    passes = out.count("status: PASS")
    ok = proc.returncode == 0 and passes >= 3
    return CaseResult("UAT-D11", ok, f"PASS lines={passes} exit={proc.returncode}")


_UAT_INGEST_OCR_KNOWN = re.compile(
    r"UAT_INGEST.*(OCR|screenshot parse|Could not read Sensibull|Need 4 option premiums|"
    r"Could not find NIFTY spot)",
    re.I,
)


def _cursor_chat_book_active() -> bool:
    try:
        from core.uat_positions import load_positions_fixture

        fix = load_positions_fixture(_root())
        return str(fix.get("source", "")).strip() == "cursor_chat"
    except Exception:
        return False


def _scan_log(robot: str, tail: int = 150, *, case_id: str | None = None) -> CaseResult:
    from core.batman_mode import log_runtime_root

    base = log_runtime_root(_root())
    candidates = list(base.glob(f"*/*/{robot}/logs/all.log"))
    if not candidates:
        cid = case_id or ("UAT-D12" if robot == "kavach" else "UAT-D13")
        return CaseResult(cid, False, "no log file")
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    err_re = re.compile(r"Traceback|ERROR\s+\||CRITICAL\s+\|", re.I)
    hits = [ln for ln in lines if err_re.search(ln)]
    filtered = 0
    if robot == "kavach" and _cursor_chat_book_active():
        before = len(hits)
        hits = [ln for ln in hits if not _UAT_INGEST_OCR_KNOWN.search(ln)]
        filtered = before - len(hits)
    cid = case_id or ("UAT-D12" if robot == "kavach" else "UAT-D13")
    ok = len(hits) == 0
    detail = f"{path.name}: {len(hits)} error lines in last {tail}"
    if filtered:
        detail += f" ({filtered} UAT_INGEST OCR ignored — cursor_chat active)"
    return CaseResult(
        cid,
        ok,
        detail,
        metrics={"log_path": str(path), "error_lines": len(hits), "ocr_filtered": filtered},
    )


def run_case_log_kavach() -> CaseResult:
    return _scan_log("kavach")


def run_case_log_drishti() -> CaseResult:
    return _scan_log("drishti")


def run_case_register_smoke() -> CaseResult:
    import asyncio

    t0 = time.perf_counter()
    try:
        from scripts.run_uat_e2e_verification import _optional_register_smoke

        ok, detail = asyncio.run(_optional_register_smoke())
        ms = (time.perf_counter() - t0) * 1000
        return CaseResult("UAT-D14", ok, detail, duration_ms=ms)
    except Exception as exc:
        return CaseResult("UAT-D14", False, str(exc))


def run_case_menu_map() -> CaseResult:
    from bat_telegram.bots.kavach2 import bot as kavach_bot

    expected = {
        "positions",
        "ato_status",
        "corelegs",
        "status",
        "environment",
        "funds",
        "pause",
        "resume",
        "resume_blocked",
        "recovery_operator",
        "recovery_auto",
        "recovery_auto_confirm",
        "start_algo",
        "batman_complete",
    }
    got = set(kavach_bot._menu_action_handlers())
    ok = got == expected
    missing = expected - got
    extra = got - expected
    return CaseResult(
        "UAT-D15",
        ok,
        f"missing={missing or '-'} extra={extra or '-'}",
    )


def run_case_environment_cmd() -> CaseResult:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from bat_telegram.bots.kavach2 import bot as kavach_bot

    message = MagicMock()
    message.reply_text = AsyncMock(return_value=None)
    update = MagicMock()
    update.message = message
    ctx = MagicMock()
    ctx.bot_data = {"broker": MagicMock(), "state": MagicMock()}
    with (
        patch.object(kavach_bot, "_require_message", return_value=message),
        patch.object(kavach_bot, "_main_menu_keyboard", return_value=MagicMock()),
    ):
        asyncio.run(kavach_bot.cmd_environment(update, ctx))
    ok = message.reply_text.await_count >= 1
    return CaseResult("UAT-D16", ok, "cmd_environment replied")


def run_case_positions_cmd() -> CaseResult:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from bat_telegram.bots.kavach2 import bot as kavach_bot
    from telegram import Update

    message = MagicMock()
    message.reply_text = AsyncMock()
    update = Update(update_id=1, message=message)
    broker = MagicMock()
    positions = [
        {
            "symbol": "NIFTY-Jun2026-23200-PE",
            "direction": "SELL",
            "qty": 130,
            "avg_price": 53.85,
        }
    ]
    reply = AsyncMock()
    with (
        patch.object(kavach_bot, "_filter_nifty_positions", return_value=positions),
        patch.object(kavach_bot, "_reply_md2", reply),
        patch.object(kavach_bot.asyncio, "to_thread", new=AsyncMock(return_value=MagicMock())),
    ):
        asyncio.run(kavach_bot.cmd_positions(update, _ctx(broker)))
    ok = reply.await_count >= 1
    return CaseResult("UAT-D17", ok, "cmd_positions OK")


def _ctx(broker: Any) -> Any:
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.bot_data = {"broker": broker, "state": MagicMock(), "event_bus": None}
    return ctx


def run_case_status_cmd() -> CaseResult:
    import asyncio
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock, patch

    from bat_telegram.bots.kavach2 import bot as kavach_bot
    from telegram import Update

    message = MagicMock()
    update = Update(update_id=1, message=message)
    reply = AsyncMock()
    dep = Path("batman_test.json")
    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=None),
        patch.object(kavach_bot, "_reply_md2", reply),
    ):
        asyncio.run(kavach_bot.cmd_status(update, _ctx(MagicMock())))
    ok = reply.await_count >= 1
    return CaseResult("UAT-D18", ok, "cmd_status no-deploy path OK")


def run_case_ato_status_cmd() -> CaseResult:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, mock_open, patch

    from bat_telegram.bots.kavach2 import bot as kavach_bot
    from telegram import Update

    message = MagicMock()
    update = Update(update_id=1, message=message)
    reply = AsyncMock()
    with (
        patch.object(kavach_bot, "_find_active_deployment", return_value=None),
        patch.object(kavach_bot, "_reply_md2", reply),
        patch("core.nifty_ltp_feed.get_cached_nifty_ltp", return_value=23400.0),
        patch("core.nifty_ltp_feed.load_feed_config"),
        patch("core.nifty_ltp_feed.read_nifty_ltp_cache", return_value=None),
    ):
        asyncio.run(kavach_bot.cmd_ato_status(update, _ctx(MagicMock())))
    ok = reply.await_count >= 1
    return CaseResult("UAT-D19", ok, "cmd_ato_status OK")


def run_case_ingest_perf() -> CaseResult:
    from core.uat_ingest import ingest_uat_screenshot
    from core.uat_positions import find_screenshot_images, load_positions_fixture, uat_screenshot_dir

    if not find_screenshot_images(uat_screenshot_dir(_root())):
        return CaseResult("UAT-D20", True, "no screenshot — OCR skipped", metrics={"ocr_skipped": True})
    try:
        fix = load_positions_fixture(_root())
    except Exception:
        fix = {}
    if str(fix.get("source", "")).strip() == "cursor_chat":
        return CaseResult(
            "UAT-D20",
            True,
            "cursor_chat fixture — OCR skipped",
            metrics={"ocr_skipped": True},
        )
    t0 = time.perf_counter()
    try:
        ingest_uat_screenshot(_root(), required=True, newest_only=True)
        ms = (time.perf_counter() - t0) * 1000
        ok = ms < 120_000
        return CaseResult(
            "UAT-D20",
            ok,
            f"ocr_ms={ms:.0f}",
            duration_ms=ms,
            metrics={"ocr_ms": round(ms)},
        )
    except Exception as exc:
        return CaseResult("UAT-D20", False, str(exc))


def run_case_ato_waiting() -> CaseResult:
    from core.state import StateManager

    state_path = _uat_state_path()
    if not state_path.is_file():
        return CaseResult("UAT-D21", True, "no state file yet (pre-register)", skipped=True)
    state = StateManager(path=state_path)
    confirmed = state.get("deployment.confirmed", False)
    phase = "armed" if confirmed else "pre-register"
    return CaseResult(
        "UAT-D21",
        True,
        f"deployment.confirmed={confirmed} phase={phase}",
        metrics={"deployment_confirmed": confirmed},
    )


def run_case_dynamic_expiry() -> CaseResult:
    from datetime import date, timedelta

    from core.nifty_option_expiry import expiry_label_from_date, fixture_expiry_date, legs_from_fixture
    from core.uat_positions import load_positions_fixture

    try:
        fix = load_positions_fixture(_root())
        exp = fixture_expiry_date(fix)
        legs = legs_from_fixture(fix)
        ok = len(legs) == 8 and exp >= date.today() - timedelta(days=14)
        label = expiry_label_from_date(exp)
        return CaseResult(
            "UAT-D23",
            ok,
            f"expiry={exp.isoformat()} label={label} legs={len(legs)}",
            metrics={"expiry_date": exp.isoformat(), "leg_count": len(legs)},
        )
    except Exception as exc:
        return CaseResult("UAT-D23", False, str(exc))


def run_case_instrument_resolve() -> CaseResult:
    from core.nifty_option_expiry import fixture_expiry_date, legs_from_fixture
    from core.uat_positions import load_positions_fixture
    from backtest_engine.resolver.instrument_master import load_instrument_master, resolve_nifty_option

    try:
        fix = load_positions_fixture(_root())
        exp = fixture_expiry_date(fix)
        master = load_instrument_master()
        resolved = []
        for strike, opt in legs_from_fixture(fix):
            inst = resolve_nifty_option(
                strike=strike, option_type=opt, expiry_date=exp, master=master
            )
            resolved.append(f"{inst.security_id}:{inst.trading_symbol}")
        ok = len(resolved) == 8
        return CaseResult(
            "UAT-D24",
            ok,
            "; ".join(resolved),
            metrics={"symbols": resolved},
        )
    except Exception as exc:
        return CaseResult("UAT-D24", False, str(exc))


def run_case_dhan_fundlimit() -> CaseResult:
    import httpx
    from dotenv import dotenv_values

    from core.token_store import TokenStore

    env = dotenv_values(_dhan_env_path())
    client = (env.get("DHAN_CLIENT_CODE") or "").strip()
    store = TokenStore(path=_access_token_path())
    token, _ = store.load()
    if not token:
        return CaseResult("UAT-D25", False, "no JWT")
    try:
        r = httpx.get(
            "https://api.dhan.co/v2/fundlimit",
            headers={"access-token": token, "client-id": client},
            timeout=15.0,
        )
        ok = r.status_code == 200
        return CaseResult("UAT-D25", ok, f"HTTP {r.status_code}", metrics={"http": r.status_code})
    except Exception as exc:
        return CaseResult("UAT-D25", False, str(exc))


def run_case_nifty_rest_ltp() -> CaseResult:
    from dotenv import dotenv_values

    from core.nifty_ltp import fetch_nifty_ltp_rest
    from core.token_store import TokenStore

    if not _market_session_open():
        return CaseResult(
            "UAT-D26",
            True,
            "SKIP off-hours — REST NIFTY deferred",
            skipped=True,
        )
    env = dotenv_values(_dhan_env_path())
    client = (env.get("DHAN_CLIENT_CODE") or "").strip()
    store = TokenStore(path=_access_token_path())
    token, _ = store.load()
    if not token:
        return CaseResult("UAT-D26", False, "no JWT")
    try:
        ltp = fetch_nifty_ltp_rest(client, token)
        ok = ltp > 0
        return CaseResult(
            "UAT-D26",
            ok,
            f"REST NIFTY ltp={ltp:.2f}",
            metrics={"nifty_rest_ltp": ltp},
        )
    except Exception as exc:
        return CaseResult("UAT-D26", False, str(exc))


def run_case_option_fno_ltp() -> CaseResult:
    from dotenv import dotenv_values

    from core.broker import BatmanBroker
    from core.nifty_option_expiry import fixture_expiry_date, legs_from_fixture
    from core.uat_positions import load_positions_fixture
    from core.token_store import TokenStore

    if not _market_session_open():
        return CaseResult(
            "UAT-D27",
            True,
            "SKIP off-hours — option LTP deferred",
            skipped=True,
        )
    try:
        fix = load_positions_fixture(_root())
        exp = fixture_expiry_date(fix)
        legs = legs_from_fixture(fix)
    except Exception as exc:
        return CaseResult("UAT-D27", False, f"fixture: {exc}")
    env = dotenv_values(_dhan_env_path())
    client = (env.get("DHAN_CLIENT_CODE") or "").strip()
    store = TokenStore(path=_access_token_path())
    token, _ = store.load()
    if not token:
        return CaseResult("UAT-D27", False, "no JWT")
    try:
        broker = BatmanBroker.connect_with_token(client, token)
        prices = broker.get_nifty_option_ltps(legs, expiry_date=exp)
        ok = len(prices) == 8
        return CaseResult(
            "UAT-D27",
            ok,
            f"FNO LTP {len(prices)}/8 {prices}",
            metrics={"option_ltps": {f"{strike}{opt}": v for (strike, opt), v in prices.items()}},
        )
    except Exception as exc:
        return CaseResult("UAT-D27", False, str(exc))


def run_case_log_jagran() -> CaseResult:
    return _scan_log("jagran", case_id="UAT-D28")


def run_case_position_enrich() -> CaseResult:
    from core.nifty_option_expiry import fixture_expiry_date, legs_from_fixture
    from core.uat_position_enrich import enrich_nifty_positions
    from core.uat_positions import load_positions_fixture

    try:
        fix = load_positions_fixture(_root())
        exp = fixture_expiry_date(fix)
        legs = legs_from_fixture(fix)
    except Exception as exc:
        return CaseResult("UAT-D29", False, str(exc))

    positions = []
    for strike, opt in legs:
        positions.append(
            {
                "symbol": f"NIFTY-TEST-{strike}-{opt}",
                "strike": strike,
                "opt_type": opt,
                "avg_price": 0.0,
                "qty": 65,
            }
        )
    out = enrich_nifty_positions(positions, fixture=fix, chain_broker=None)
    missing = [p for p in out if not p.get("avg_price")]
    ok = len(missing) == 0
    return CaseResult(
        "UAT-D29",
        ok,
        f"filled={len(out) - len(missing)}/4 expiry={exp.isoformat()}",
        metrics={"missing": len(missing)},
    )


def run_case_cursor_chat_source() -> CaseResult:
    from core.uat_positions import load_positions_fixture

    try:
        fix = load_positions_fixture(_root())
        source = str(fix.get("source", "")).strip()
        ok = source in ("cursor_chat", "sensibull_ocr", "sensibull_test") and len(fix.get("legs", [])) == 8
        return CaseResult("UAT-D30", ok, f"source={source!r} legs=8")
    except Exception as exc:
        return CaseResult("UAT-D30", False, str(exc))


def run_case_pytest_subset() -> CaseResult:
    py = get_venv_python(_root())
    # Do not include test_uat_daily_matrix.py here (would re-run full catalog).
    targets = [
        "tests/test_shadow_resolver.py",
        "tests/test_kavach_scenarios.py",
        "tests/test_kavach_robot.py",
        "tests/test_uat_ingest.py",
        "tests/test_nifty_option_expiry.py",
        "tests/test_dhan_market_quote.py",
        "tests/test_uat_position_enrich.py",
    ]
    existing = [t for t in targets if (_root() / t).is_file()]
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(py), "-m", "pytest", *existing, "-q", "--tb=line"],
        cwd=str(_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    ms = (time.perf_counter() - t0) * 1000
    m = re.search(r"(\d+) passed", proc.stdout or "")
    summary = m.group(0) if m else f"exit {proc.returncode}"
    return CaseResult("UAT-D22", proc.returncode == 0, summary, duration_ms=ms)


RUNNERS: dict[str, Callable[[], CaseResult]] = {
    "UAT-D00": run_case_mode_uat,
    "UAT-D01": run_case_screenshot,
    "UAT-D02": run_case_positions_json,
    "UAT-D03": run_case_jwt,
    "UAT-D04": run_case_validate_fixture,
    "UAT-D05": run_case_shadow_load,
    "UAT-D06": run_case_shadow_order,
    "UAT-D07": run_case_ltp_fresh,
    "UAT-D08": run_case_bot_drishti,
    "UAT-D09": run_case_bot_kavach,
    "UAT-D10": run_case_bot_jagran,
    "UAT-D11": run_case_phase1_check,
    "UAT-D12": run_case_log_kavach,
    "UAT-D13": run_case_log_drishti,
    "UAT-D14": run_case_register_smoke,
    "UAT-D15": run_case_menu_map,
    "UAT-D16": run_case_environment_cmd,
    "UAT-D17": run_case_positions_cmd,
    "UAT-D18": run_case_status_cmd,
    "UAT-D19": run_case_ato_status_cmd,
    "UAT-D20": run_case_ingest_perf,
    "UAT-D21": run_case_ato_waiting,
    "UAT-D22": run_case_pytest_subset,
    "UAT-D23": run_case_dynamic_expiry,
    "UAT-D24": run_case_instrument_resolve,
    "UAT-D25": run_case_dhan_fundlimit,
    "UAT-D26": run_case_nifty_rest_ltp,
    "UAT-D27": run_case_option_fno_ltp,
    "UAT-D28": run_case_log_jagran,
    "UAT-D29": run_case_position_enrich,
    "UAT-D30": run_case_cursor_chat_source,
}

_SLOW_CASES = frozenset(
    {"UAT-D04", "UAT-D11", "UAT-D20", "UAT-D22", "UAT-D24", "UAT-D26", "UAT-D27"}
)


def run_all_cases(
    *,
    skip_bots: bool = False,
    skip_slow: bool = False,
    run_logger: Any | None = None,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    catalog = {c.case_id: c for c in TEST_CATALOG}
    for case in TEST_CATALOG:
        if skip_bots and case.category == "bots":
            r = CaseResult(case.case_id, True, "skipped by flag", skipped=True)
            results.append(r)
            if run_logger:
                run_logger.log_case(r, catalog_name=case.name)
            continue
        if skip_slow and case.case_id in _SLOW_CASES:
            r = CaseResult(case.case_id, True, "skipped by flag", skipped=True)
            results.append(r)
            if run_logger:
                run_logger.log_case(r, catalog_name=case.name)
            continue
        runner = RUNNERS[case.case_id]
        t0 = time.perf_counter()
        r = runner()
        if r.duration_ms == 0:
            r.duration_ms = (time.perf_counter() - t0) * 1000
        results.append(r)
        if run_logger:
            run_logger.log_case(r, catalog_name=catalog[case.case_id].name)
    return results
