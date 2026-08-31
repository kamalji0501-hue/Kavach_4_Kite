"""Live snapshot for the Kavach web desk."""

from __future__ import annotations

from typing import Any

from web.runtime import get_runtime


def _state_get(state: Any, key: str, default: Any = None) -> Any:
    if state is None:
        return default
    try:
        return state.get(key, default)
    except Exception:
        return default



def _pnl_exit_snap(state: Any) -> dict[str, Any]:
    try:
        from core.pnl_exit_guard import snapshot_pnl_exit

        return snapshot_pnl_exit(state)
    except Exception:
        return {
            "safe_on": False,
            "safe_level_rs": None,
            "tp_on": False,
            "tp_level_rs": None,
            "firing": False,
            "last_reason": None,
            "last_pnl": None,
            "last_at": None,
        }

def snapshot() -> dict[str, Any]:
    rt = get_runtime()
    state = rt.state if rt else None
    nifty = ""
    nifty_ltp = None
    nifty_ok = False
    try:
        from web.arm import nifty_ltp as live_nifty
        from core.nifty_ltp_feed import cache_consumer_status, default_cache_path

        px = live_nifty()
        if px is not None and float(px) > 0:
            nifty_ltp = float(px)
            nifty = f"{nifty_ltp:,.2f}"
        nifty_ok, _ = cache_consumer_status(path=default_cache_path())
    except Exception:
        nifty = ""
        nifty_ltp = None
    dep = bool(_state_get(state, "deployment.confirmed", False))
    paused = bool(_state_get(state, "algo.paused", False))
    day_pnl = None
    positions = []
    try:
        from core.day_pnl_cache import cached_day_pnl, cached_positions, refresh_hybrid_day_pnl

        if rt and rt.broker:
            try:
                refresh_hybrid_day_pnl(broker=rt.broker)
            except Exception:
                pass
        day_pnl = cached_day_pnl()
        positions = cached_positions() or []
    except Exception:
        day_pnl = None
        positions = []

    ato_readiness: dict[str, Any] = {}
    try:
        from core.ato_readiness import compute_ato_readiness

        ato_readiness = compute_ato_readiness(state=state, positions=positions)
    except Exception as exc:
        ato_readiness = {
            "armed": False,
            "blocked_reasons": ["readiness_error"],
            "hard_blocked_reasons": ["readiness_error"],
            "summary_line": f"ATO BLOCKED — readiness error: {exc}",
            "feed": {"ready": nifty_ok, "ltp": nifty_ltp, "age_s": None},
        }

    return {
        "ok": True,
        "broker": bool(rt and rt.broker),
        "paused": paused,
        "pause_reason": _state_get(state, "algo.pause_reason"),
        "deployment": dep,
        "ce_ato": bool(_state_get(state, "ato.ce_ato_active") or _state_get(state, "ato.ce_triggered")),
        "pe_ato": bool(_state_get(state, "ato.pe_ato_active") or _state_get(state, "ato.pe_triggered")),
        "ce_symbol": _state_get(state, "ato.ce_protect_symbol") or "",
        "pe_symbol": _state_get(state, "ato.pe_protect_symbol") or "",
        "dyn_hedge": bool(_state_get(state, "dyn_hedge.exit_enabled", False)),
        "nifty": nifty,
        "nifty_ltp": nifty_ltp,
        "nifty_ok": nifty_ok,
        "order_mode": _state_get(state, "order_mode") or "paper",
        "day_pnl": day_pnl,
        "positions": positions,
        "ato_readiness": ato_readiness,
        "ato_buy_fill_token": _state_get(state, "ato.web_buy_fill_token") or "",
        "ato_sell_fill_token": _state_get(state, "ato.web_sell_fill_token") or "",
        "pnl_exit": _pnl_exit_snap(state),
    }
