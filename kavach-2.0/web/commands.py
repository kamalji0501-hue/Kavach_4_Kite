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
        ("pe_dyn_hedge", "PE 35%DYN"),
        ("pe_sell", "PE SELL"),
        ("ce_buy", "CE BUY"),
        ("ce_margin_hedge", "CE MARGIN"),
        ("ce_dyn_hedge", "CE 35%DYN"),
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
    from core.desk_alerts import emit_desk_alert

    row = emit_desk_alert(
        severity="orange",
        category="ATO blocked",
        alert="Kavach is paused — tap Resume when the feed is healthy.",
        log="Algo paused. ATO monitoring suspended.",
    )
    out = {"ok": True, "text": "Algo paused. ATO monitoring suspended."}
    if row:
        out["desk_alert"] = row
    return out


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
    from core.desk_alerts import tag_result

    return tag_result(
        {"ok": True, "text": "Algo resumed."},
        category="ATO ready",
        ok_alert="ATO is armed again — feed is OK.",
    )


def dyn_hedge_get() -> dict[str, Any]:
    st = _state()
    enabled = bool(st.get("dyn_hedge.exit_enabled", False)) if st else False
    return {
        "ok": True,
        "enabled": enabled,
        "text": (
            "35% Dynamic Hedge\n"
            "Exit 35% qty when ATO triggers?\n"
            f"Current: {'YES' if enabled else 'NO'}"
        ),
    }


def dyn_hedge_set(enabled: bool) -> dict[str, Any]:
    st = _state()
    if st:
        st.set("dyn_hedge.exit_enabled", bool(enabled))
    out = dyn_hedge_get()
    from core.desk_alerts import tag_result

    return tag_result(
        out,
        category="Desk",
        ok_alert="Dynamic hedge is on." if enabled else "Dynamic hedge is off.",
    )


def batman_complete(*, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        return {
            "ok": True,
            "need_confirm": True,
            "text": (
                "This stops ATO and clears Kavach state for this deployment.\n"
                "Broker positions are left as-is on Zerodha.\n"
                "\n"
                "IMPORTANT: Square off any open legs manually on the broker terminal — Kavach will not exit them."
            ),
        }
    dep = _active_deployment()
    st = _state()
    if dep:
        try:
            from core.batman_mode import deployments_dir

            archive = deployments_dir(_root()) / "archive"
            archive.mkdir(parents=True, exist_ok=True)
            dest = archive / dep.name
            dep.replace(dest)
        except Exception as exc:
            logger.warning("archive deploy failed: %s", exc)
    elif st is None:
        return {"ok": False, "error": "No active deployment to complete."}
    if st:
        try:
            from core.batman_cleanup import reset_state_after_complete

            reset_state_after_complete(st)
        except Exception as exc:
            logger.warning("batman_complete state reset failed: %s", exc)
            try:
                st.set("deployment.confirmed", False)
                st.set("algo.paused", False)
                st.set("ato.ce_ato_active", False)
                st.set("ato.pe_ato_active", False)
            except Exception:
                pass
    from core.desk_alerts import tag_result

    return tag_result(
        {"ok": True, "text": "Batman complete. Deployment archived. Positions on Zerodha were not closed."},
        category="Deploy",
        ok_alert="Batman deploy finished.",
    )


def buffer_get() -> dict[str, Any]:
    from web.arm import buffer_form
    return buffer_form()


def buffer_set(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import buffer_save
    from core.desk_alerts import tag_result

    return tag_result(
        buffer_save(payload),
        category="Desk",
        ok_alert="Buffer levels saved.",
        fail_alert="Buffer save failed.",
    )


def poll_get() -> dict[str, Any]:
    from web.arm import poll_form
    return poll_form()


def poll_set(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import poll_save
    from core.desk_alerts import tag_result

    out = poll_save(payload)
    secs = out.get("poll_interval") if isinstance(out, dict) else None
    ok_line = f"Poll time saved ({secs}s)." if secs is not None else "Poll time saved."
    return tag_result(out, category="Desk", ok_alert=ok_line, fail_alert="Poll save failed.")


def register_defaults(expiry: str | None = None) -> dict[str, Any]:
    from web.arm import register_defaults as _rd
    return _rd(expiry)


def register_batman(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import register_batman as _rb
    from core.desk_alerts import tag_result

    return tag_result(
        _rb(payload),
        category="Desk",
        ok_alert="Batman is armed.",
        fail_severity="orange",
        fail_alert="Batman arm failed.",
    )


def deploy_defaults(expiry: str | None = None) -> dict[str, Any]:
    from web.arm import deploy_defaults as _dd
    return _dd(expiry)


def deploy_preview(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import deploy_preview as _dp
    return _dp(payload)


def deploy_batman(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import deploy_batman as _db
    from core.desk_alerts import tag_result

    if not payload.get("confirm"):
        return _db(payload)
    out = _db(payload)
    fail_sev = "red"
    err = str((out or {}).get("error") or "")
    if "token" in err.lower() or "broker" in err.lower():
        cat = "Tokens"
        fail_line = "Kite token is off — live orders are blocked until you save a new one."
    else:
        cat = "Deploy"
        fail_line = err or "Batman deploy failed."
    return tag_result(
        out,
        category="Desk" if (out or {}).get("ok") else cat,
        ok_alert="Batman deploy finished.",
        fail_severity=fail_sev,
        fail_alert=fail_line,
    )


def deploy_and_register_batman(payload: dict[str, Any]) -> dict[str, Any]:
    from web.arm import deploy_and_register_batman as _dar
    from core.desk_alerts import tag_result

    out = _dar(payload)
    err = str((out or {}).get("error") or "")
    if (out or {}).get("ok"):
        return tag_result(
            out,
            category="Desk",
            ok_alert="Deploy sent and Register armed successfully.",
        )
    return tag_result(
        out,
        category="Deploy",
        ok_alert="Deploy sent and Register armed successfully.",
        fail_severity="red",
        fail_alert=err or "Deploy completed, but Register was not started.",
    )


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
    from core.desk_alerts import tag_result

    return tag_result(
        {"ok": True, "text": "JWT refreshed via TOTP and saved for Kavach + Feeder."},
        category="Tokens",
        ok_alert="Dhan login saved.",
    )


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
    from core.desk_alerts import tag_result

    return tag_result(
        {"ok": True, "text": "Dhan JWT saved for Kavach and Feeder."},
        category="Tokens",
        ok_alert="Dhan login saved.",
    )


def token_deactivate() -> dict[str, Any]:
    from core.token_fanout import clear_dhan_jwt

    clear_dhan_jwt(root=_root())
    from core.desk_alerts import tag_result

    return tag_result(
        {"ok": True, "text": "Dhan token deactivated on Kavach + Feeder files."},
        category="Tokens",
        ok_alert="Dhan token was turned off.",
    )


def token_zerodha(token: str) -> dict[str, Any]:
    from core.token_fanout import persist_zerodha_token
    from core.zerodha_token_exchange import resolve_kite_access_token

    try:
        access, detail = resolve_kite_access_token(token)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    persist_zerodha_token(
        access,
        root=_root(),
        source="kavach_web",
        user_id=str(detail) if detail not in ("ok", "") else "",
    )
    from core.desk_alerts import tag_result

    return tag_result(
        {
            "ok": True,
            "text": f"Zerodha token exchanged and saved (last4=····{access[-4:]}). Feeder + Kavach updated.",
        },
        category="Tokens",
        ok_alert="Kite token saved.",
    )


def token_zerodha_deactivate() -> dict[str, Any]:
    from core.token_fanout import clear_zerodha_token
    from core.zerodha_credentials import clear_live_order_broker

    clear_zerodha_token(root=_root())
    try:
        clear_live_order_broker()
    except Exception:
        pass
    from core.desk_alerts import emit_desk_alert

    row = emit_desk_alert(
        severity="red",
        category="Tokens",
        alert="Kite token is off — live orders are blocked until you save a new one.",
        log="Zerodha token deactivated on Kavach + Feeder files.",
    )
    out = {"ok": True, "text": "Zerodha token deactivated on Kavach + Feeder files."}
    if row:
        out["desk_alert"] = row
    return out


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


def payoff_graph() -> dict[str, Any]:
    from web.payoff import payoff_snapshot

    return payoff_snapshot()
