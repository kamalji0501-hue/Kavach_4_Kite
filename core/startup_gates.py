"""Sequential Phase 1 startup gates (DRISHTI → KAVACH → JAGRAN)."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.bot_process_status import BotRunState, classify_bot
from core.nifty_ltp_feed import cache_consumer_status
from core.utils import is_trading_day

ROOT = Path(__file__).resolve().parents[1]
_IST = ZoneInfo("Asia/Kolkata")
_DEFAULT_LTP_MAX_AGE = 90.0


def _nifty_cache_path(root: Path) -> Path:
    from core.batman_mode import nifty_ltp_cache_path

    return nifty_ltp_cache_path(root)


def nifty_cache_age_seconds(*, root: Path | None = None) -> float | None:
    """Return age of NIFTY LTP cache in seconds, or None if missing/unparseable."""
    path = _nifty_cache_path(root or ROOT)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cache_age_seconds") is not None:
            return float(payload["cache_age_seconds"])
        updated = payload.get("updated_at") or payload.get("timestamp")
        if not updated:
            return None
        ts = datetime.fromisoformat(str(updated))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_IST)
        return max(0.0, (datetime.now(_IST) - ts.astimezone(_IST)).total_seconds())
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def wait_bot_running(
    robot: str,
    *,
    timeout_seconds: float = 120.0,
    poll_seconds: float = 3.0,
    root: Path | None = None,
) -> bool:
    """Poll until *robot* reports RUNNING or timeout."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if classify_bot(robot, root=root or ROOT).state is BotRunState.RUNNING:
            return True
        time.sleep(poll_seconds)
    return False


def ltp_gate_skip_reason(*, now: datetime | None = None) -> str | None:
    """Return why the live LTP gate is skipped, or None when live prices are required."""
    current = now or datetime.now(_IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_IST)
    else:
        current = current.astimezone(_IST)

    if not is_trading_day(current.date()):
        return "off_calendar_day"
    local = current.time()
    if local.hour < 9 or (local.hour == 9 and local.minute < 14):
        return "pre_market"
    if local.hour > 15 or (local.hour == 15 and local.minute > 35):
        return "post_market"
    return None


def wait_drishti_ltp_ready(
    *,
    timeout_seconds: float = 90.0,
    max_age_seconds: float = _DEFAULT_LTP_MAX_AGE,
    poll_seconds: float = 3.0,
    root: Path | None = None,
) -> tuple[bool, str]:
    """Wait for DRISHTI RUNNING + fresh NIFTY cache (skipped off-hours / holidays)."""
    base = root or ROOT
    skip_reason = ltp_gate_skip_reason()
    if skip_reason == "off_calendar_day":
        return True, "off_calendar_day — LTP gate skipped"
    if skip_reason == "pre_market":
        return True, "pre_market — LTP gate skipped"
    if skip_reason == "post_market":
        return True, "post_market — LTP gate skipped"

    if not wait_bot_running("drishti", timeout_seconds=min(60.0, timeout_seconds), root=base):
        return False, "DRISHTI not RUNNING within gate timeout"

    deadline = time.monotonic() + timeout_seconds
    cache_path = _nifty_cache_path(base)
    while time.monotonic() < deadline:
        ok, detail = cache_consumer_status(path=cache_path, max_age_seconds=max_age_seconds)
        if ok:
            return True, detail
        time.sleep(poll_seconds)

    ok, detail = cache_consumer_status(path=cache_path, max_age_seconds=max_age_seconds)
    if ok:
        return True, detail
    return False, detail
