"""Single source of truth: ATO ARMED vs BLOCKED for web, Telegram, health."""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger("batman.ato_readiness")

_SERVICE_CACHE: dict[str, tuple[float, bool]] = {}
_SERVICE_TTL_S = 10.0


def _svc_active(name: str) -> bool:
    now = time.monotonic()
    hit = _SERVICE_CACHE.get(name)
    if hit and (now - hit[0]) < _SERVICE_TTL_S:
        return hit[1]
    try:
        cp = subprocess.run(
            ["systemctl", "is-active", name],
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
        active = cp.stdout.strip() == "active"
    except Exception:
        active = False
    _SERVICE_CACHE[name] = (now, active)
    return active


def _state_get(state: Any, key: str, default: Any = None) -> Any:
    if state is None:
        return default
    try:
        return state.get(key, default)
    except Exception:
        return default


def _protect_qty(positions: list[dict[str, Any]] | None, symbol: str) -> int:
    if not symbol or not positions:
        return 0
    sym = str(symbol).strip().upper()
    total = 0
    for row in positions:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").strip().upper() != sym:
            continue
        try:
            total += int(row.get("qty") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _levels_from_state(state: Any) -> dict[str, Any]:
    """Best-effort absolute NIFTY levels; blank strings when unknown."""
    out = {
        "pe_entry": "",
        "pe_exit": "",
        "ce_entry": "",
        "ce_exit": "",
        "protect_symbol_pe": str(_state_get(state, "ato.pe_protect_symbol") or ""),
        "protect_symbol_ce": str(_state_get(state, "ato.ce_protect_symbol") or ""),
        "protect_broker_qty_pe": 0,
        "protect_broker_qty_ce": 0,
    }
    try:
        from web.arm import buffer_form

        form = buffer_form()
        if isinstance(form, dict):
            out["pe_entry"] = str(form.get("pe_entry") or "")
            out["pe_exit"] = str(form.get("pe_retrace") or "")
            out["ce_entry"] = str(form.get("ce_entry") or "")
            out["ce_exit"] = str(form.get("ce_retrace") or "")
    except Exception:
        pass
    return out


def compute_ato_readiness(
    *,
    state: Any = None,
    positions: list[dict[str, Any]] | None = None,
    datafeedbot_service: str = "datafeedbot.service",
    kavach2_service: str = "batman-kavach2.service",
    check_services: bool = True,
) -> dict[str, Any]:
    """Return ARMED/BLOCKED snapshot. Pure local file/state reads — no market REST."""
    from core.feeder_ipc import feeder_socket_ready
    from core.nifty_ltp_feed import (
        cache_consumer_status,
        consumer_max_age_for_trading,
        default_cache_path,
        read_nifty_ltp_cache,
    )

    reasons: list[str] = []
    reason_labels: dict[str, str] = {}

    snap = read_nifty_ltp_cache(default_cache_path())
    ready, detail = cache_consumer_status(path=default_cache_path())
    age_s: float | None = None
    ltp: float | None = None
    source = ""
    collector = ""
    feed_healthy = False
    if snap is not None:
        try:
            age_s = float(snap.age_seconds())
        except Exception:
            age_s = None
        try:
            ltp = float(snap.ltp) if snap.ltp is not None else None
        except (TypeError, ValueError):
            ltp = None
        source = str(getattr(snap, "source", "") or "")
        collector = str(getattr(snap, "collector", "") or "") or "feeder"
        feed_healthy = bool(getattr(snap, "feed_healthy", False))
    else:
        collector = "feeder"

    socket_ok = False
    try:
        socket_ok = bool(feeder_socket_ready())
    except Exception:
        socket_ok = False

    if snap is None:
        reasons.append("nifty_cache_missing")
        reason_labels["nifty_cache_missing"] = "NIFTY cache missing — check Datafeedbot"
    elif not ready:
        reasons.append("nifty_cache_stale")
        age_txt = f"{age_s:.0f}s" if age_s is not None else "?"
        reason_labels["nifty_cache_stale"] = (
            f"NIFTY cache stale {age_txt} — check Datafeedbot"
        )
    elif not feed_healthy:
        reasons.append("feed_unhealthy")
        reason_labels["feed_unhealthy"] = "NIFTY feed_healthy=false — check Datafeedbot"

    if not socket_ok:
        reasons.append("feeder_ipc_down")
        reason_labels["feeder_ipc_down"] = "Feeder IPC socket down (market.sock)"

    dfb_ok = True
    kav_ok = True
    if check_services:
        dfb_ok = _svc_active(datafeedbot_service)
        kav_ok = _svc_active(kavach2_service)
        if not dfb_ok:
            reasons.append("datafeedbot_down")
            reason_labels["datafeedbot_down"] = "datafeedbot.service inactive"
        if not kav_ok:
            reasons.append("kavach2_down")
            reason_labels["kavach2_down"] = "batman-kavach2.service inactive"

    deployment = bool(_state_get(state, "deployment.confirmed", False))
    if not deployment:
        reasons.append("deployment_not_confirmed")
        reason_labels["deployment_not_confirmed"] = (
            "Deployment not confirmed — Register / Arm Kavach first"
        )

    paused = bool(_state_get(state, "algo.paused", False))
    pause_reason = _state_get(state, "algo.pause_reason")
    if paused:
        reasons.append("algo_paused")
        reason_labels["algo_paused"] = "KAVACH PAUSED"

    pe_halted = bool(_state_get(state, "ato.pe_side_halted", False))
    ce_halted = bool(_state_get(state, "ato.ce_side_halted", False))
    pe_halt_reason = _state_get(state, "ato.pe_halt_reason")
    ce_halt_reason = _state_get(state, "ato.ce_halt_reason")
    manage_raw = str(_state_get(state, "ato.manage_sides") or "both").strip().lower()
    if manage_raw in ("pe", "pe_only"):
        manage = "pe"
    elif manage_raw in ("ce", "ce_only"):
        manage = "ce"
    else:
        manage = "both"

    if pe_halted and manage in ("pe", "both"):
        reasons.append("pe_side_halted")
        reason_labels["pe_side_halted"] = (
            f"PE side halted ({pe_halt_reason or 'halted'})"
        )
    if ce_halted and manage in ("ce", "both"):
        reasons.append("ce_side_halted")
        reason_labels["ce_side_halted"] = (
            f"CE side halted ({ce_halt_reason or 'halted'})"
        )

    # All managed sides halted → cannot fire
    if manage == "pe" and pe_halted:
        pass  # already in reasons
    elif manage == "ce" and ce_halted:
        pass
    elif manage == "both" and pe_halted and ce_halted:
        if "all_sides_halted" not in reasons:
            reasons.append("all_sides_halted")
            reason_labels["all_sides_halted"] = "CE and PE sides both halted"

    levels = _levels_from_state(state)
    pe_sym = levels["protect_symbol_pe"]
    ce_sym = levels["protect_symbol_ce"]
    pe_qty = _protect_qty(positions, pe_sym)
    ce_qty = _protect_qty(positions, ce_sym)
    levels["protect_broker_qty_pe"] = pe_qty
    levels["protect_broker_qty_ce"] = ce_qty

    pe_active = bool(
        _state_get(state, "ato.pe_ato_active")
        or _state_get(state, "ato.pe_triggered")
    )
    ce_active = bool(
        _state_get(state, "ato.ce_ato_active")
        or _state_get(state, "ato.ce_triggered")
    )
    if pe_active and pe_qty > 0 and manage in ("pe", "both"):
        reasons.append("pe_protect_in_book")
        reason_labels["pe_protect_in_book"] = (
            f"PE protect already in book ({pe_sym} qty={pe_qty})"
        )
    if ce_active and ce_qty > 0 and manage in ("ce", "both"):
        reasons.append("ce_protect_in_book")
        reason_labels["ce_protect_in_book"] = (
            f"CE protect already in book ({ce_sym} qty={ce_qty})"
        )

    outside_window = False
    try:
        from core.ato_monitoring_schedule import is_past_monitoring_start

        if not is_past_monitoring_start():
            outside_window = True
            reasons.append("outside_monitoring_window")
            reason_labels["outside_monitoring_window"] = (
                "Outside ATO monitoring window"
            )
    except Exception:
        pass

    # Hard gates that mean ATO will NOT fire a new protect on breach
    hard = {
        "nifty_cache_missing",
        "nifty_cache_stale",
        "feed_unhealthy",
        "feeder_ipc_down",
        "datafeedbot_down",
        "kavach2_down",
        "deployment_not_confirmed",
        "algo_paused",
        "outside_monitoring_window",
        "all_sides_halted",
    }
    if manage == "pe" and "pe_side_halted" in reasons:
        hard.add("pe_side_halted")
    if manage == "ce" and "ce_side_halted" in reasons:
        hard.add("ce_side_halted")
    if manage == "both" and pe_halted and ce_halted:
        hard.add("pe_side_halted")
        hard.add("ce_side_halted")

    # If every managed side already has protect in book, treat as blocked for new BUY
    pe_blocked_book = "pe_protect_in_book" in reasons or (
        manage == "pe" and pe_halted
    )
    ce_blocked_book = "ce_protect_in_book" in reasons or (
        manage == "ce" and ce_halted
    )
    if manage == "pe" and pe_blocked_book and "pe_protect_in_book" in reasons:
        hard.add("pe_protect_in_book")
    if manage == "ce" and ce_blocked_book and "ce_protect_in_book" in reasons:
        hard.add("ce_protect_in_book")
    if manage == "both":
        pe_done = "pe_protect_in_book" in reasons or pe_halted
        ce_done = "ce_protect_in_book" in reasons or ce_halted
        if pe_done and ce_done:
            hard.add("pe_protect_in_book")
            hard.add("ce_protect_in_book")

    hard_hits = [r for r in reasons if r in hard]
    armed = len(hard_hits) == 0

    if armed:
        pe_e = levels.get("pe_entry") or "?"
        summary = f"ATO ARMED — PE entry <= {pe_e}" if manage != "ce" else (
            f"ATO ARMED — CE entry >= {levels.get('ce_entry') or '?'}"
        )
        if manage == "both":
            summary = (
                f"ATO ARMED — PE entry <= {pe_e} · "
                f"CE entry >= {levels.get('ce_entry') or '?'}"
            )
    else:
        top = hard_hits[:2]
        labels = [reason_labels.get(r, r) for r in top]
        summary = "ATO BLOCKED — " + "; ".join(labels)

    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")

    return {
        "armed": armed,
        "blocked_reasons": list(reasons),
        "hard_blocked_reasons": hard_hits,
        "reason_labels": reason_labels,
        "feed": {
            "ready": bool(ready),
            "ltp": ltp,
            "age_s": age_s,
            "source": source or "unknown",
            "collector": collector or "feeder",
            "socket_ready": socket_ok,
            "feed_healthy": feed_healthy,
            "detail": detail,
            "max_age_s": float(consumer_max_age_for_trading()),
        },
        "ops": {
            "deployment_confirmed": deployment,
            "algo_paused": paused,
            "pause_reason": pause_reason,
            "pe_side_halted": pe_halted,
            "pe_halt_reason": pe_halt_reason,
            "ce_side_halted": ce_halted,
            "ce_halt_reason": ce_halt_reason,
            "manage_sides": manage,
            "outside_monitoring_window": outside_window,
            "pe_ato_active": pe_active,
            "ce_ato_active": ce_active,
        },
        "ato_levels": levels,
        "services": {
            "datafeedbot_active": dfb_ok,
            "kavach2_active": kav_ok,
        },
        "summary_line": summary,
        "checked_at": checked_at,
    }


def ato_readiness_snapshot(*, state: Any = None) -> dict[str, Any]:
    """Convenience for web/health — loads positions cache when present."""
    positions: list[dict[str, Any]] | None = None
    try:
        from core.day_pnl_cache import cached_positions

        positions = cached_positions() or []
    except Exception:
        positions = None
    if state is None:
        try:
            from web.runtime import get_runtime

            rt = get_runtime()
            state = rt.state if rt else None
        except Exception:
            state = None
    if state is None:
        try:
            from core.batman_mode import state_path, workspace_root
            from core.state import StateManager

            state = StateManager(path=state_path(workspace_root()))
        except Exception:
            state = None
    return compute_ato_readiness(state=state, positions=positions)
