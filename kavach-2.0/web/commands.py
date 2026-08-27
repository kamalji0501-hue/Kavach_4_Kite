"""Kavach web commands — same actions as Telegram buttons, no second strategy."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from web.runtime import require_runtime

logger = logging.getLogger("batman.kavach.web.commands")


def _state():
    return require_runtime().state


def _root() -> Path:
    return require_runtime().root


def _active_deployment() -> Path | None:
    try:
        from core.batman_mode import deployments_dir

        dep_dir = deployments_dir(_root())
    except Exception:
        return None
    if not dep_dir.is_dir():
        return None
    files = sorted(
        [p for p in dep_dir.glob("batman_*.json") if p.parent.name != "archive"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def kavach_status() -> dict[str, Any]:
    rt = require_runtime()
    st = rt.state
    dep = _active_deployment()
    paused = bool(st.get("algo.paused", False)) if st else False
    ce = bool(st.get("ato.ce_triggered") or st.get("ato.ce_ato_active")) if st else False
    pe = bool(st.get("ato.pe_triggered") or st.get("ato.pe_ato_active")) if st else False
    try:
        from core.feed_recovery import format_nifty_feed_status_line
        from core.ato_monitoring_schedule import format_monitoring_schedule_line

        nifty = format_nifty_feed_status_line()
        schedule = format_monitoring_schedule_line(deployed=bool(dep))
    except Exception as exc:
        nifty, schedule = str(exc), ""
    text = (
        f"KAVACH Status\n"
        f"Broker     : {'Connected' if rt.broker else 'No broker'}\n"
        f"Algo       : {'Paused' if paused else ('Running' if dep else 'Idle')}\n"
        f"Deployment : {dep.name if dep else 'Not deployed'}\n"
        f"ATO Schedule: {schedule}\n"
        f"NIFTY Feed : {nifty}\n"
        f"ATO CE     : {'Triggered' if ce else 'Idle'}\n"
        f"ATO PE     : {'Triggered' if pe else 'Idle'}"
    )
    return {"ok": True, "text": text}


def ato_status() -> dict[str, Any]:
    st = _state()
    dep = _active_deployment()
    if not dep:
        return {
            "ok": True,
            "text": "No active deployment. Tap Register to arm Batman.",
            "ce_protect": "N/A",
            "pe_protect": "N/A",
            "manage": "—",
            "deployed": False,
        }
    ce = "N/A"
    pe = "N/A"
    manage_raw = "both"
    if st:
        ce = str(st.get("ato.ce_protect_symbol") or "N/A")
        pe = str(st.get("ato.pe_protect_symbol") or "N/A")
        manage_raw = str(st.get("ato.manage_sides") or "both").strip().lower()
    manage_label = {
        "pe": "PE",
        "ce": "CE",
        "both": "BOTH",
    }.get(manage_raw, manage_raw.upper() or "—")
    lines = [
        f"CE protect : {ce}",
        f"PE protect : {pe}",
        f"Manage     : {manage_label}",
    ]
    return {
        "ok": True,
        "text": "\n".join(lines),
        "ce_protect": ce,
        "pe_protect": pe,
        "manage": manage_label,
        "deployed": True,
    }


def core_legs() -> dict[str, Any]:
    dep = _active_deployment()
    if not dep:
        return {"ok": True, "text": "No active deployment. Tap Register first."}
    try:
        data = json.loads(dep.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    p = data.get("positions") or {}
    order = [
        ("pe_buy", "PE BUY"),
        ("pe_margin_hedge", "PE MARGIN"),
        ("pe_dyn_hedge", "PE 30%DYN"),
        ("pe_sell", "PE SELL"),
        ("ce_buy", "CE BUY"),
        ("ce_margin_hedge", "CE MARGIN"),
        ("ce_dyn_hedge", "CE 30%DYN"),
        ("ce_sell", "CE SELL"),
    ]
    lines = ["Core Batman Legs", ""]
    for key, label in order:
        leg = p.get(key) or {}
        if leg:
            lines.append(
                f"{label}: {leg.get('symbol', '?')}  qty={leg.get('qty', '?')}  avg=Rs {leg.get('avg_price', '?')}"
            )
    return {"ok": True, "text": "\n".join(lines) if len(lines) > 2 else "No legs in deployment."}


def environment() -> dict[str, Any]:
    from core.environment_display import environment_short_message

    return {"ok": True, "text": environment_short_message()}


def ato_positions() -> dict[str, Any]:
    rt = require_runtime()
    st = rt.state
    ce = (st.get("ato.ce_protect_symbol") if st else None) or ""
    pe = (st.get("ato.pe_protect_symbol") if st else None) or ""
    lines = ["ATO Positions", ""]
    if not ce and not pe:
        lines.append("No ATO protect legs registered.")
        return {"ok": True, "text": "\n".join(lines)}
    lines.append(f"CE {ce or '-'} triggered={bool(st.get('ato.ce_triggered')) if st else False}")
    lines.append(f"PE {pe or '-'} triggered={bool(st.get('ato.pe_triggered')) if st else False}")
    return {"ok": True, "text": "\n".join(lines)}


def pause() -> dict[str, Any]:
    if not _active_deployment():
        return {"ok": False, "error": "No deployment registered."}
    st = _state()
    if st:
        st.set("algo.paused", True)
        st.set("algo.pause_reason", "kavach2_web")
        st.set("algo.paused_by", "kavach2_web")
    bus = require_runtime().event_bus
    if bus:
        try:
            from core.event_bus import Event

            bus.publish(Event.MODULE_STOPPED, {"module": "ato_protection", "by": "kavach_web_pause"})
        except Exception:
            pass
    return {"ok": True, "text": "Algo paused. ATO monitoring suspended."}


def resume() -> dict[str, Any]:
    if not _active_deployment():
        return {"ok": False, "error": "No deployment. Register first."}
    st = _state()
    pause_reason = st.get("algo.pause_reason") if st else None
    try:
        from core.feed_recovery import evaluate_kavach_resume

        allowed, note = evaluate_kavach_resume(pause_reason)
        if not allowed:
            return {"ok": False, "error": note}
    except Exception:
        pass
    if st:
        from core.ato_side_state import clear_resumable_side_halts

        st.set("algo.paused", False)
        st.set("algo.pause_reason", None)
        st.set("algo.paused_at", None)
        st.set("algo.paused_by", None)
        cleared = clear_resumable_side_halts(st)
        if cleared:
            st.set("ato.resume_reevaluate", True)
    bus = require_runtime().event_bus
    if bus:
        try:
            from core.event_bus import Event

            bus.publish(Event.MODULE_STARTED, {"module": "ato_protection", "by": "kavach_web_resume"})
        except Exception:
            pass
    return {"ok": True, "text": "Algo resumed."}


def dyn_hedge_get() -> dict[str, Any]:
    st = _state()
    enabled = bool(st.get("dyn_hedge.exit_enabled", False)) if st else False
    return {
        "ok": True,
        "enabled": enabled,
        "text": (
            "30% Dynamic Hedge\n"
            "Exit 30% qty when ATO triggers?\n"
            f"Current: {'YES' if enabled else 'NO'}"
        ),
    }


def dyn_hedge_set(enabled: bool) -> dict[str, Any]:
    st = _state()
    if st:
        st.set("dyn_hedge.exit_enabled", bool(enabled))
    return dyn_hedge_get()


def batman_complete(*, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        return {
            "ok": True,
            "need_confirm": True,
            "text": (
                "Batman Complete?\n"
                "This will stop ATO, archive the deployment, and clear state.\n"
                "Zerodha positions are NOT closed automatically."
            ),
        }
    dep = _active_deployment()
    if not dep:
        return {"ok": False, "error": "No active deployment to complete."}
    st = _state()
    try:
        from core.batman_mode import deployments_dir

        archive = deployments_dir(_root()) / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        dest = archive / dep.name
        dep.replace(dest)
    except Exception as exc:
        logger.warning("archive deploy failed: %s", exc)
    if st:
        try:
            st.set("deployment.confirmed", False)
            st.set("algo.paused", False)
            st.set("ato.ce_ato_active", False)
            st.set("ato.pe_ato_active", False)
        except Exception:
            pass
    return {"ok": True, "text": "Batman complete. Deployment archived. Positions on Zerodha were not closed."}


def buffer_get() -> dict[str, Any]:
    from web.arm import buffer_form
    return buffer_form()


def buffer_set(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import buffer_save
    return buffer_save(payload)


def poll_get() -> dict[str, Any]:
    from web.arm import poll_form
    return poll_form()


def poll_set(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import poll_save
    return poll_save(payload)


def register_defaults() -> dict[str, Any]:
    from web.arm import register_defaults as _rd
    return _rd()


def register_batman(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import register_batman as _rb
    return _rb(payload)


def deploy_defaults() -> dict[str, Any]:
    from web.arm import deploy_defaults as _dd
    return _dd()


def deploy_preview(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import deploy_preview as _dp
    return _dp(payload)


def deploy_batman(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import deploy_batman as _db
    return _db(payload)


def ato_combined() -> dict[str, Any]:
    from web.arm import ato_combined as _ato
    return _ato()


def token_status() -> dict[str, Any]:
    from bat_telegram.bots.kavach2.token_ui import token_snapshot, token_summary

    snap = token_snapshot(root=_root())
    snap["ok"] = True
    snap["text"] = token_summary(root=_root())
    return snap


def token_refresh() -> dict[str, Any]:
    from core.dhan_totp import renew_and_save

    token = renew_and_save(root=_root())
    return {"ok": True, "text": "JWT refreshed via TOTP and saved for Kavach + Feeder."}


def token_paste(jwt: str) -> dict[str, Any]:
    from bat_telegram.bots.kavach2 import token_ui
    from core.token_fanout import persist_dhan_jwt
    from core.token_store import TokenStore

    tok = (jwt or "").strip()
    if not token_ui.is_jwt(tok):
        return {"ok": False, "error": "That does not look like a Dhan JWT."}
    persist_dhan_jwt(tok, root=_root(), source="kavach_web")
    try:
        from core.batman_mode import access_token_path
        from core.token_store import TokenStore

        TokenStore(path=access_token_path(_root())).save(tok)
    except Exception as exc:
        logger.warning("token store save: %s", exc)
    return {"ok": True, "text": "Dhan JWT saved for Kavach and Feeder."}


def token_deactivate() -> dict[str, Any]:
    from core.token_fanout import clear_dhan_jwt

    clear_dhan_jwt(root=_root())
    return {"ok": True, "text": "Dhan token deactivated on Kavach + Feeder files."}


def token_zerodha(token: str) -> dict[str, Any]:
    from core.token_fanout import persist_zerodha_token

    persist_zerodha_token((token or "").strip(), root=_root(), source="kavach_web")
    return {"ok": True, "text": "Zerodha feeder token saved."}


def register_note() -> dict[str, Any]:
    return {
        "ok": True,
        "text": (
            "Register Batman is a multi-step wizard (strikes, qty, paper/live).\n"
            "Use this page for status; finish the numbered steps in Telegram if a "
            "conversation is already open, or start Register from Telegram.\n"
            "Web Buffer Manager below can still tune ATO buffers after Register."
        ),
    }


def deploy_note() -> dict[str, Any]:
    return {
        "ok": True,
        "text": (
            "Deploy Batman 2.0 is the 8-leg punch wizard.\n"
            "Confirm legs in Telegram Deploy Batman 2.0 — same backend, no second strategy."
        ),
    }
