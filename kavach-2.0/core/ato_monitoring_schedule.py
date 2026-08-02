"""KAVACH ATO monitoring schedule — when breach checks may run (default 09:25 IST).

Live NSE session: breach checks only after the configured start (09:25) during
09:15–15:30. UAT exception: when DRISHTI is feeding ``uat_replay`` into the
shared NIFTY cache, ATO may run off-hours so evening Virtual tests can fire.
"""

from __future__ import annotations

import json
import zoneinfo
from datetime import datetime, time as dt_time
from pathlib import Path

from core.nifty_ltp_feed import is_nse_market_session

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_DEFAULT_START = "09:25"
_PARAMS_PATH = (
    Path(__file__).resolve().parent.parent / "telegram" / "bots" / "kavach" / "params.json"
)
_UAT_REPLAY_SOURCE = "uat_replay"


def monitoring_start_hhmm() -> str:
    """Configured monitoring start time as ``HH:MM`` (IST)."""
    try:
        raw = json.loads(_PARAMS_PATH.read_text(encoding="utf-8"))
        block = raw.get("ato_monitoring") or {}
        return str(block.get("start_time_ist", _DEFAULT_START))
    except Exception:
        return _DEFAULT_START


def monitoring_start_time() -> dt_time:
    hhmm = monitoring_start_hhmm()
    hour, minute = (int(x) for x in hhmm.split(":", 1))
    return dt_time(hour, minute)


def is_uat_replay_feed_active(now: datetime | None = None) -> bool:
    """True in UAT when DRISHTI shared cache is a fresh ``uat_replay`` tick."""
    try:
        from core.batman_mode import is_uat
        from core.nifty_ltp_feed import consumer_max_age_for_trading, read_nifty_ltp_cache
    except Exception:
        return False

    if not is_uat():
        return False
    snap = read_nifty_ltp_cache()
    if snap is None:
        return False
    if str(snap.source).strip().lower() != _UAT_REPLAY_SOURCE:
        return False
    return snap.is_fresh(consumer_max_age_for_trading(), now)


def is_past_monitoring_start(now: datetime | None = None) -> bool:
    """True when live-session ATO may poll, or UAT replay feed is active off-hours."""
    now = now or datetime.now(_IST)
    if is_uat_replay_feed_active(now):
        return True
    if not is_nse_market_session(now):
        return False
    return now.time() >= monitoring_start_time()


def is_waiting_for_monitoring_start(
    now: datetime | None = None,
    *,
    deployed: bool = True,
) -> bool:
    """True when deployment is armed but breach checks must not run yet."""
    if not deployed:
        return False
    now = now or datetime.now(_IST)
    if is_uat_replay_feed_active(now):
        return False
    if not is_nse_market_session(now):
        return False
    return now.time() < monitoring_start_time()


def ato_session_open_for_breach(now: datetime | None = None) -> bool:
    """True when the ATO poll loop may run breach checks (market hours or UAT replay)."""
    now = now or datetime.now(_IST)
    if is_uat_replay_feed_active(now):
        return True
    from core import utils

    return utils.is_market_hours()


def format_monitoring_schedule_line(
    *,
    deployed: bool = True,
    now: datetime | None = None,
) -> str:
    """One-line schedule summary for Telegram Status (plain text — escape for MD2)."""
    start = monitoring_start_hhmm()
    now = now or datetime.now(_IST)
    if not deployed:
        return "Not armed — deploy to schedule monitoring"
    if is_uat_replay_feed_active(now):
        return "▶ Monitoring active (UAT replay)"
    if is_waiting_for_monitoring_start(now, deployed=deployed):
        return f"⏳ Waiting — monitoring starts at {start} IST"
    if is_past_monitoring_start(now):
        return f"▶ Monitoring active (from {start} IST)"
    return f"⏳ Armed — monitoring starts at {start} IST on session open"
