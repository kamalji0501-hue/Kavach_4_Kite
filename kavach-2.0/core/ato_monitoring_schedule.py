"""KAVACH ATO monitoring schedule — when breach checks may run.

Live NSE session defaults:
  start 09:20 IST (or immediately after overnight morning handoff completes)
  end   15:25 IST (no new ATO protect buys after this, hedge or not)

Full NSE cash tape remains 09:15–15:30; only ATO monitoring closes at 15:25.
UAT exception: when DRISHTI is feeding ``uat_replay`` into the shared NIFTY
cache, ATO may run off-hours so evening Virtual tests can fire.
"""

from __future__ import annotations

import json
import zoneinfo
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any

from core.nifty_ltp_feed import is_nse_market_session

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_DEFAULT_START = "09:20"
_DEFAULT_END = "15:25"
_PARAMS_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "telegram" / "bots" / "kavach2" / "params.json",
    Path(__file__).resolve().parent.parent / "telegram" / "bots" / "kavach" / "params.json",
)
_UAT_REPLAY_SOURCE = "uat_replay"


def _ato_monitoring_block() -> dict[str, Any]:
    for path in _PARAMS_CANDIDATES:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            block = raw.get("ato_monitoring") or {}
            if isinstance(block, dict):
                return block
        except Exception:
            continue
    return {}


def _hhmm_to_time(hhmm: str, default: str) -> dt_time:
    raw = str(hhmm or default).strip() or default
    hour, minute = (int(x) for x in raw.split(":", 1))
    return dt_time(hour, minute)


def monitoring_start_hhmm() -> str:
    """Configured monitoring start time as ``HH:MM`` (IST)."""
    try:
        return str(_ato_monitoring_block().get("start_time_ist", _DEFAULT_START))
    except Exception:
        return _DEFAULT_START


def monitoring_end_hhmm() -> str:
    """Configured monitoring end time as ``HH:MM`` (IST). Default 15:25."""
    try:
        return str(_ato_monitoring_block().get("end_time_ist", _DEFAULT_END))
    except Exception:
        return _DEFAULT_END


def monitoring_start_time() -> dt_time:
    return _hhmm_to_time(monitoring_start_hhmm(), _DEFAULT_START)


def monitoring_end_time() -> dt_time:
    return _hhmm_to_time(monitoring_end_hhmm(), _DEFAULT_END)


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


def _overnight_early_unlock(now: datetime, state: Any | None) -> bool:
    """After morning overnight hedges exit, skip waiting for configured start (legacy early-unlock)."""
    try:
        from core.overnight_handoff import morning_handoff_completed_today
    except Exception:
        return False
    today = now.astimezone(_IST).date().isoformat() if now.tzinfo else now.date().isoformat()
    if state is not None:
        return morning_handoff_completed_today(state, today)
    # Best-effort for web/readiness when no State object was passed.
    try:
        from core.batman_mode import state_path, workspace_root
        from core.state import StateManager

        st = StateManager(path=state_path(workspace_root()))
        return morning_handoff_completed_today(st, today)
    except Exception:
        return False


def is_past_monitoring_end(now: datetime | None = None) -> bool:
    """True at/after ATO monitoring end (default 15:25 IST) on a live session day."""
    now = now or datetime.now(_IST)
    if is_uat_replay_feed_active(now):
        return False
    if not is_nse_market_session(now):
        # Off hours after the cash close also count as past end for messaging.
        t = now.time()
        return t > monitoring_end_time()
    return now.time() > monitoring_end_time()


def is_past_monitoring_start(now: datetime | None = None, *, state: Any | None = None) -> bool:
    """True when live-session ATO may poll, or UAT replay feed is active off-hours."""
    now = now or datetime.now(_IST)
    if is_uat_replay_feed_active(now):
        return True
    if not is_nse_market_session(now):
        return False
    if now.time() > monitoring_end_time():
        return False
    if _overnight_early_unlock(now, state):
        return True
    return now.time() >= monitoring_start_time()


def is_waiting_for_monitoring_start(
    now: datetime | None = None,
    *,
    deployed: bool = True,
    state: Any | None = None,
) -> bool:
    """True when deployment is armed but breach checks must not run yet."""
    if not deployed:
        return False
    now = now or datetime.now(_IST)
    if is_uat_replay_feed_active(now):
        return False
    if not is_nse_market_session(now):
        return False
    if now.time() > monitoring_end_time():
        return False
    if _overnight_early_unlock(now, state):
        return False
    return now.time() < monitoring_start_time()


def ato_session_open_for_breach(now: datetime | None = None) -> bool:
    """True when the ATO poll loop may run breach checks (ATO window or UAT replay).

    ATO window is 09:15–15:25 IST on trading days (end is configurable; default 15:25).
    Hedge buy / deny does not extend this — monitoring always ends at end_time.
    """
    now = now or datetime.now(_IST)
    if is_uat_replay_feed_active(now):
        return True
    if not is_nse_market_session(now):
        return False
    return now.time() <= monitoring_end_time()


def format_monitoring_schedule_line(
    *,
    deployed: bool = True,
    now: datetime | None = None,
    state: Any | None = None,
) -> str:
    """One-line schedule summary for Telegram Status (plain text — escape for MD2)."""
    start = monitoring_start_hhmm()
    end = monitoring_end_hhmm()
    now = now or datetime.now(_IST)
    if not deployed:
        return "Not armed — deploy to schedule monitoring"
    if is_uat_replay_feed_active(now):
        return "▶ Monitoring active (UAT replay)"
    if is_nse_market_session(now) and now.time() > monitoring_end_time():
        return f"⏹ Monitoring closed for day (ends {end} IST)"
    if is_waiting_for_monitoring_start(now, deployed=deployed, state=state):
        return f"⏳ Waiting — monitoring starts at {start} IST"
    if is_past_monitoring_start(now, state=state):
        if _overnight_early_unlock(now, state) and now.time() < monitoring_start_time():
            return f"▶ Monitoring active (overnight handoff done — before {start}; ends {end})"
        return f"▶ Monitoring active ({start}–{end} IST)"
    return f"⏳ Armed — monitoring {start}–{end} IST on session open"
