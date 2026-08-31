"""Shared NIFTY feed recovery ownership — DRISHTI and KAVACH read the same flags.

Prevents dual control during outages: either DRISHTI auto-recovery drives ATO
resume, or the operator takes over manually via KAVACH Resume.
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime
from pathlib import Path
from typing import Any

from core.algo_control import is_algo_paused
from core.batman_mode import state_path, workspace_root
from core.nifty_ltp_feed import load_feed_config, read_nifty_ltp_cache
from core.state import StateManager

logger = logging.getLogger("batman.feed_recovery")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def default_state_path() -> Path:
    """Mode-aware batman_state.json (UAT → data/uat/batman_state.json)."""
    return state_path(workspace_root())

OWNER_DRISHTI = "drishti"  # legacy alias; prefer OWNER_FEEDER on Feeder-only VPS
OWNER_FEEDER = "feeder"
OWNER_OPERATOR = "operator"

ALERT_INTERVAL_SECONDS = 30
ESCALATION_SECONDS = 300
TRANSPORT_CYCLE_LIMIT = 4
AUTO_RESUME_STABLE_SECONDS = 45

LABEL_MANUAL_HANDLING = "Manual handling"
LABEL_AUTO_RESUME = "Auto resume"
LABEL_WAITING_FOR_FEED = "Waiting for feed"

FEED_RELATED_PAUSE_REASONS = frozenset(
    {
        "nifty_ltp_websocket_failed",
        "nifty_ltp_rest_fallback_failed",
        "nifty_ltp_feed_failure",
        "nifty_ltp_feed_stale",
        "nifty_ltp_stale_price",
        "nifty_ltp_cache_stale",
    }
)


def _sm(state_path: Path | str | None = None) -> StateManager:
    return StateManager(
        path=Path(state_path) if state_path else default_state_path()
    )


def _recovery_blob(sm: StateManager) -> dict[str, Any]:
    raw = sm.get("nifty_feed_recovery")
    if not isinstance(raw, dict):
        raw = {}
    return raw


def _save_blob(sm: StateManager, blob: dict[str, Any]) -> None:
    sm.set("nifty_feed_recovery", blob)


def get_recovery_owner(state_path: Path | str | None = None) -> str:
    blob = _recovery_blob(_sm(state_path))
    owner = str(blob.get("owner", OWNER_FEEDER))
    if owner == OWNER_DRISHTI:
        return OWNER_FEEDER  # surface Feeder on this VPS
    return owner if owner in (OWNER_FEEDER, OWNER_OPERATOR, OWNER_DRISHTI) else OWNER_FEEDER


def set_recovery_owner(
    owner: str,
    *,
    by: str = "feeder",
    state_path: Path | str | None = None,
) -> None:
    if owner not in (OWNER_DRISHTI, OWNER_FEEDER, OWNER_OPERATOR):
        raise ValueError(f"invalid recovery owner: {owner}")
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    now = datetime.now(_IST).isoformat()
    blob["owner"] = owner
    blob["owner_set_at"] = now
    blob["owner_set_by"] = by
    if owner in (OWNER_DRISHTI, OWNER_FEEDER):
        blob["escalation_sent"] = False
    _save_blob(sm, blob)
    logger.info("NIFTY feed recovery owner=%s (by=%s)", owner, by)


def feed_incident_severity(
    explicit: str = "critical",
    *,
    state_path: Path | str | None = None,
) -> str:
    """Downgrade to warning when operator chose manual handling."""
    if get_recovery_owner(state_path) == OWNER_OPERATOR and explicit.lower() == "critical":
        return "warning"
    return explicit


def record_transport_switch(*, state_path: Path | str | None = None) -> int:
    """Count WS↔REST alternations (one full cycle = 4 switches)."""
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    count = int(blob.get("transport_switch_count", 0)) + 1
    blob["transport_switch_count"] = count
    if count >= TRANSPORT_CYCLE_LIMIT:
        blob["transport_cycle_exhausted"] = True
    _save_blob(sm, blob)
    return count


def is_transport_cycle_exhausted(state_path: Path | str | None = None) -> bool:
    return bool(_recovery_blob(_sm(state_path)).get("transport_cycle_exhausted"))


def should_send_degraded_status_alert(state_path: Path | str | None = None) -> bool:
    """Silent retry until 5-minute escalation (no 30s spam)."""
    if is_transport_cycle_exhausted(state_path):
        return False
    return should_send_escalation(state_path)


def mark_feed_degraded(*, state_path: Path | str | None = None) -> None:
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    now = datetime.now(_IST).isoformat()
    if not blob.get("degraded_since"):
        blob["degraded_since"] = now
    blob["degraded"] = True
    blob["operator_ready_notified"] = False
    blob["kavach_resume_ready_notified"] = False
    blob["feed_ready_since"] = None
    if not blob.get("transport_switch_count"):
        blob["transport_switch_count"] = 0
    _save_blob(sm, blob)


def clear_recovery_on_batman_complete(*, state_path: Path | str | None = None) -> None:
    """Full recovery reset when Batman session ends (clean slate for next deploy)."""
    sm = _sm(state_path)
    sm.set("nifty_feed_recovery", None)
    logger.info("NIFTY feed recovery state cleared on batman_complete")


def format_nifty_feed_status_line(*, state_path: Path | str | None = None) -> str:
    """One-line NIFTY feed summary for KAVACH Status (plain text — escape for MD2)."""
    from core.nifty_ltp_failover import cache_transport_label

    snap = read_nifty_ltp_cache()
    ready, age = is_nifty_cache_trading_ready()
    degraded = is_feed_degraded(state_path)
    transport = cache_transport_label(snap)

    if snap and snap.ltp > 0:
        price_part = f"₹{snap.ltp:,.2f} ({snap.age_seconds():.0f}s)"
    elif age is not None:
        price_part = f"no LTP ({age:.0f}s stale)"
    else:
        price_part = "no cache"

    if degraded:
        return f"⚠️ {price_part} — degraded"
    if ready:
        return f"✅ {price_part} — {transport}"
    return f"⚠️ {price_part} — {transport}"


def clear_recovery_at_eod(*, state_path: Path | str | None = None) -> bool:
    """Reset recovery owner/flags after market close (does not unpause ATO)."""
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    owner = get_recovery_owner(state_path)
    degraded = bool(blob.get("degraded"))
    if owner in (OWNER_DRISHTI, OWNER_FEEDER) and not degraded:
        return False
    set_recovery_owner(OWNER_FEEDER, by="eod_reset", state_path=state_path)
    clear_feed_degraded(state_path=state_path)
    logger.info("NIFTY feed recovery state cleared at EOD")
    return True


def clear_feed_degraded(*, state_path: Path | str | None = None) -> None:
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    blob["degraded"] = False
    blob["degraded_since"] = None
    blob["escalation_sent"] = False
    blob["last_alert_at"] = None
    blob["operator_ready_notified"] = False
    blob["kavach_resume_ready_notified"] = False
    blob["transport_switch_count"] = 0
    blob["transport_cycle_exhausted"] = False
    blob["feed_ready_since"] = None
    _save_blob(sm, blob)


def update_feed_ready_stability(*, ready: bool, state_path: Path | str | None = None) -> None:
    """Track consecutive trading-ready cache for sustained auto-resume."""
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    if ready:
        if not blob.get("feed_ready_since"):
            blob["feed_ready_since"] = datetime.now(_IST).isoformat()
    else:
        blob["feed_ready_since"] = None
    _save_blob(sm, blob)


def feed_ready_stable_seconds(state_path: Path | str | None = None) -> float | None:
    blob = _recovery_blob(_sm(state_path))
    since = blob.get("feed_ready_since")
    if not since:
        return None
    try:
        return max(0.0, (datetime.now(_IST) - datetime.fromisoformat(since)).total_seconds())
    except (TypeError, ValueError):
        return None


def can_auto_resume_feed_recovery(state_path: Path | str | None = None) -> bool:
    """Auto-resume only after feed has been trading-ready for a stable window."""
    if not should_auto_resume_ato(state_path):
        return False
    stable = feed_ready_stable_seconds(state_path)
    return stable is not None and stable >= float(AUTO_RESUME_STABLE_SECONDS)


def should_notify_kavach_resume_ready(state_path: Path | str | None = None) -> bool:
    """One-shot: feed ready for trading while ATO still paused (feed recovery)."""
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    if blob.get("kavach_resume_ready_notified"):
        return False
    if not is_algo_paused(state_path):
        return False
    reason = sm.get("algo.pause_reason")
    if not is_feed_recovery_context(reason, state_path=state_path):
        return False
    ready, _ = is_nifty_cache_trading_ready()
    if not ready:
        return False
    blob["kavach_resume_ready_notified"] = True
    _save_blob(sm, blob)
    return True


def should_notify_operator_feed_ready(state_path: Path | str | None = None) -> bool:
    """One-shot: operator owns recovery, feed is fresh, ATO still paused."""
    if get_recovery_owner(state_path) != OWNER_OPERATOR:
        return False
    if not is_algo_paused(state_path):
        return False
    ready, _ = is_nifty_cache_trading_ready()
    if not ready:
        return False
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    if blob.get("operator_ready_notified"):
        return False
    blob["operator_ready_notified"] = True
    blob["degraded"] = False
    blob["degraded_since"] = None
    blob["escalation_sent"] = False
    blob["last_alert_at"] = None
    _save_blob(sm, blob)
    return True


def is_feed_degraded(state_path: Path | str | None = None) -> bool:
    return bool(_recovery_blob(_sm(state_path)).get("degraded"))


def should_auto_resume_ato(state_path: Path | str | None = None) -> bool:
    """Feeder/legacy Drishti owner may auto-resume when it owns recovery."""
    return get_recovery_owner(state_path) in (OWNER_FEEDER, OWNER_DRISHTI)


def should_send_recovery_alert(
    *,
    interval_seconds: float = ALERT_INTERVAL_SECONDS,
    state_path: Path | str | None = None,
) -> bool:
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    if not blob.get("degraded"):
        return True
    last = blob.get("last_alert_at")
    if not last:
        blob["last_alert_at"] = datetime.now(_IST).isoformat()
        _save_blob(sm, blob)
        return True
    try:
        elapsed = (datetime.now(_IST) - datetime.fromisoformat(last)).total_seconds()
    except (TypeError, ValueError):
        elapsed = interval_seconds
    if elapsed >= interval_seconds:
        blob["last_alert_at"] = datetime.now(_IST).isoformat()
        _save_blob(sm, blob)
        return True
    return False


def degraded_duration_seconds(state_path: Path | str | None = None) -> float | None:
    blob = _recovery_blob(_sm(state_path))
    since = blob.get("degraded_since")
    if not since:
        return None
    try:
        return max(0.0, (datetime.now(_IST) - datetime.fromisoformat(since)).total_seconds())
    except (TypeError, ValueError):
        return None


def should_send_escalation(state_path: Path | str | None = None) -> bool:
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    if not blob.get("degraded") or blob.get("escalation_sent"):
        return False
    if get_recovery_owner(state_path) not in (OWNER_FEEDER, OWNER_DRISHTI):
        return False
    duration = degraded_duration_seconds(state_path)
    if duration is None or duration < ESCALATION_SECONDS:
        return False
    blob["escalation_sent"] = True
    _save_blob(sm, blob)
    return True


def is_nifty_cache_trading_ready() -> tuple[bool, float | None]:
    """True when cache has a fresh, healthy LTP for ATO."""
    cfg = load_feed_config()
    snap = read_nifty_ltp_cache()
    if cfg is None or snap is None or snap.ltp <= 0 or not snap.feed_healthy:
        return False, snap.age_seconds() if snap else None
    max_age = cfg.consumer_max_age_seconds()
    if not snap.is_fresh(max_age):
        return False, snap.age_seconds()
    return True, snap.age_seconds()


def is_feed_recovery_context(
    pause_reason: str | None,
    *,
    state_path: Path | str | None = None,
) -> bool:
    """True when pause is from NIFTY feed failure (not manual KAVACH pause)."""
    _ = state_path
    return bool(pause_reason and pause_reason in FEED_RELATED_PAUSE_REASONS)


def is_kavach_resume_blocked_for_feed(
    pause_reason: str | None,
    *,
    state_path: Path | str | None = None,
) -> bool:
    """Resume must stay disabled until cache is trading-ready (feed recovery only)."""
    if not is_algo_paused(state_path):
        return False
    if not is_feed_recovery_context(pause_reason, state_path=state_path):
        return False
    ready, _ = is_nifty_cache_trading_ready()
    return not ready


def kavach_resume_button_spec(
    pause_reason: str | None,
    *,
    state_path: Path | str | None = None,
) -> tuple[str, str]:
    """Label and menu action for KAVACH Resume (Telegram cannot grey out buttons)."""
    if is_kavach_resume_blocked_for_feed(pause_reason, state_path=state_path):
        return LABEL_WAITING_FOR_FEED, "resume_blocked"
    return "Resume", "resume"


def show_recovery_control_buttons(
    pause_reason: str | None,
    *,
    state_path: Path | str | None = None,
) -> bool:
    """Show I'm handling this / Auto recovery during an active feed outage."""
    if not is_algo_paused(state_path):
        return False
    if not is_feed_recovery_context(pause_reason, state_path=state_path):
        return False
    ready, _ = is_nifty_cache_trading_ready()
    return not ready or is_feed_degraded(state_path)


def evaluate_kavach_resume(
    pause_reason: str | None,
    *,
    state_path: Path | str | None = None,
) -> tuple[bool, str]:
    """Whether KAVACH Resume is allowed and a user-facing reason.

    Returns (allowed, message). Empty message when allowed without extra note.
    Manual KAVACH pause (non-feed) ignores feed cache checks.
    """
    ready, age = is_nifty_cache_trading_ready()

    if not is_feed_recovery_context(pause_reason, state_path=state_path):
        return True, ""

    if ready:
        if get_recovery_owner(state_path) == OWNER_OPERATOR:
            set_recovery_owner(OWNER_FEEDER, by="kavach_resume_healthy", state_path=state_path)
        clear_feed_degraded(state_path=state_path)
        return True, ""

    age_txt = f"{age:.0f}s" if age is not None else "unknown"
    return (
        False,
        f"NIFTY feed cache is not ready (age {age_txt}). Datafeedbot / Feeder is still "
        "recovering. Tap <b>Manual handling</b> on KAVACH if you "
        "are fixing it yourself — Kavach will notify when the feed is back.",
    )


def is_past_kavach_monitoring_start(now: datetime | None = None) -> bool:
    from core.ato_monitoring_schedule import is_past_monitoring_start

    return is_past_monitoring_start(now)


def try_session_open_auto_resume(*, state_path: Path | str | None = None) -> str | None:
    """After KAVACH monitoring start (default 09:25): auto-resume if feed healthy.

    Returns ``auto_resumed``, ``notify_operator``, or None.
    """
    if not is_past_kavach_monitoring_start():
        return None
    sm = _sm(state_path)
    blob = _recovery_blob(sm)
    today = datetime.now(_IST).date().isoformat()
    if blob.get("session_open_handled_date") == today:
        return None
    if not is_algo_paused(state_path):
        blob["session_open_handled_date"] = today
        _save_blob(sm, blob)
        return None
    reason = sm.get("algo.pause_reason")
    if not is_feed_recovery_context(reason, state_path=state_path):
        return None
    ready, _ = is_nifty_cache_trading_ready()
    if not ready:
        return None

    blob["session_open_handled_date"] = today
    _save_blob(sm, blob)
    if should_auto_resume_ato(state_path):
        from core.algo_control import resume_algo

        if resume_algo(state_path=state_path):
            clear_feed_degraded(state_path=state_path)
            logger.info("ATO auto-resumed at session open — feed healthy")
            return "auto_resumed"
    return "notify_operator"
