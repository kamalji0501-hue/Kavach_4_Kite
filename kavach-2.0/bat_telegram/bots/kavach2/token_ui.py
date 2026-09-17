"""Kavach2 Token UI — GO-parity Dhan JWT paste / TOTP refresh / status / deactivate."""

from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Any

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core.batman_mode import access_token_path, secrets_dhan_env_path, workspace_root
from core.token_fanout import clear_dhan_jwt, persist_dhan_jwt
from core.token_store import TokenStore

logger = logging.getLogger("batman.kavach2.token")

AWAITING_KAVACH_TOKEN_KEY = "awaiting_kavach_dhan_token"


def _root(context: ContextTypes.DEFAULT_TYPE | None = None) -> Any:
    if context is not None:
        return context.bot_data.get("workspace_root") or workspace_root()
    return workspace_root()


def token_store(root: Any = None) -> TokenStore:
    return TokenStore(path=access_token_path(root))


def is_jwt(text: str) -> bool:
    t = (text or "").strip()
    return len(t) > 30 and not t.startswith("/") and " " not in t and "." in t


def set_awaiting_token(context: ContextTypes.DEFAULT_TYPE | None, value: bool) -> None:
    if context is not None:
        context.user_data[AWAITING_KAVACH_TOKEN_KEY] = value


def is_awaiting_token(context: ContextTypes.DEFAULT_TYPE | None) -> bool:
    if context is None:
        return False
    return bool(context.user_data.get(AWAITING_KAVACH_TOKEN_KEY, False))


def resolve_client_code(context: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    if context is not None:
        cached = str(context.bot_data.get("client_code") or "").strip()
        if cached:
            return cached
        root = context.bot_data.get("workspace_root")
    else:
        root = None
    try:
        from dotenv import load_dotenv

        load_dotenv(secrets_dhan_env_path(root) if root else secrets_dhan_env_path())
    except Exception:
        pass
    code = os.environ.get("DHAN_CLIENT_CODE", "").strip()
    if context is not None and code:
        context.bot_data["client_code"] = code
    return code


def apply_token_runtime(context: ContextTypes.DEFAULT_TYPE, token: str, client_code: str) -> bool:
    """Hot-reload Kavach broker after TokenStore save."""
    from core.broker_factory import create_broker

    root = _root(context)
    broker = context.bot_data.get("broker")
    connected = False
    try:
        if broker is not None and hasattr(broker, "hot_reload_token"):
            broker.hot_reload_token(client_code, token)
            connected = True
        else:
            broker = create_broker(client_code, token, root)
            context.bot_data["broker"] = broker
            connected = True
    except Exception as exc:
        logger.warning("Kavach broker reload after token save failed: %s", exc)
        try:
            broker = create_broker(client_code, token, root)
            context.bot_data["broker"] = broker
            connected = True
        except Exception as exc2:
            logger.error("Kavach broker create after token save failed: %s", exc2)
            connected = False
    return connected


def clear_token_runtime(context: ContextTypes.DEFAULT_TYPE) -> None:
    root = _root(context)
    try:
        from core import dhan_totp

        dhan_totp.set_auto_renew_enabled(False, root)
    except Exception as exc:
        logger.warning("Kavach disable TOTP auto-renew failed: %s", exc)
    try:
        clear_dhan_jwt(root=root)
    except Exception as exc:
        logger.warning("Kavach/Feeder Dhan JWT clear failed: %s", exc)
    context.bot_data["broker"] = None


def token_summary(store: TokenStore | None = None, *, root: Any = None) -> str:
    from bat_telegram.bots.kavach2 import zerodha_feeder_token as ztok

    ts = store or token_store(root)
    tok, saved_at = ts.load()
    try:
        from core import dhan_totp

        totp_block = dhan_totp.status_html(root) if hasattr(dhan_totp, "status_html") else ""
    except Exception:
        totp_block = ""
    try:
        z_line = ztok.status_html()
    except Exception:
        z_line = "Feeder Zerodha: status unavailable"

    if not tok:
        parts = ["🔑 <b>Token Status</b>", "", "🔴 <b>No Dhan JWT stored</b>"]
        if totp_block:
            parts.extend(["", totp_block])
        parts.extend(["", z_line])
        return "\n".join(parts)

    age_h = ts.token_age_hours() or 0
    expires_in = ts.effective_expires_in_hours()
    if expires_in is None:
        expires_in = max(0.0, 24.0 - age_h)
    saved_fmt = saved_at.strftime("%d-%b %H:%M") if saved_at else "unknown"
    jwt_exp = ts.jwt_expires_at_local()
    jwt_line = jwt_exp.strftime("%d-%b %H:%M %Z") if jwt_exp else "N/A"
    if expires_in > 12:
        status_icon, status_text = "🟢", "Healthy"
    elif expires_in > 4:
        status_icon, status_text = "🟡", "Expiring Soon"
    elif expires_in > 0:
        status_icon, status_text = "🟠", "Critical"
    else:
        status_icon, status_text = "🔴", "Expired"
    progress_percent = min(100, int((expires_in / 24.0) * 100))
    filled_blocks = int(progress_percent / 10)
    empty_blocks = 10 - filled_blocks
    progress_bar = "█" * filled_blocks + "░" * empty_blocks
    parts = [
        "🔑 <b>Token Status</b>",
        "",
        f"{status_icon} <b>{status_text}</b>",
        "",
        f"🕒 <b>Age:</b> {age_h:.1f} hours",
        f"⏳ <b>Expires in:</b> {expires_in:.1f} hours",
        f"🔐 <b>JWT exp:</b> {html.escape(jwt_line)}",
        f"📅 <b>Saved at:</b> {html.escape(saved_fmt)} IST",
        "",
        "📊 <b>Lifetime Progress</b>",
        f"[{progress_bar}] {progress_percent}%",
        "",
        "Saved for <b>Kavach</b> and <b>Feeder</b>.",
    ]
    if totp_block:
        parts.extend(["", totp_block])
    parts.extend(["", z_line])
    return "\n".join(parts)



def _nifty_spot() -> dict[str, Any]:
    try:
        from core.nifty_ltp_feed import read_nifty_ltp_cache

        snap = read_nifty_ltp_cache()
        if snap is not None and float(getattr(snap, "ltp", 0) or 0) > 0:
            return {
                "ltp": float(snap.ltp),
                "source": str(getattr(snap, "source", "") or ""),
            }
    except Exception:
        pass
    return {"ltp": None, "source": ""}


def _zerodha_spot(*, root: Any = None) -> dict[str, Any]:
    from core.token_fanout import feeder_zerodha_json_path, kavach_zerodha_json_path
    from bat_telegram.bots.kavach2.zerodha_feeder_token import _read_json_status

    tok, saved = _read_json_status(kavach_zerodha_json_path(root))
    if not tok:
        tok, saved = _read_json_status(feeder_zerodha_json_path())
    last4 = tok[-4:] if tok and len(tok) >= 4 else ""
    return {
        "present": bool(tok),
        "saved_at": saved or "",
        "last4": last4,
    }


def token_snapshot(*, root: Any = None) -> dict[str, Any]:
    """Structured TOKEN page payload (GO-parity fields, no raw JWT)."""
    ts = token_store(root)
    tok, saved_at = ts.load()
    totp: dict[str, Any] = {
        "configured": False,
        "auto_renew": False,
        "days_left": None,
        "policy_days": 30,
        "secret_marked": "",
        "last_refresh": "never",
        "last_ok": None,
        "last_error": None,
    }
    try:
        from core import dhan_totp

        creds = dhan_totp.load_credentials(root)
        days_left, configured, days_policy = dhan_totp.totp_days_remaining(root)
        meta = dhan_totp.load_meta(root)
        last = dhan_totp._parse_ist(meta.get("last_refresh_at"))
        totp = {
            "configured": bool(creds.configured),
            "auto_renew": bool(dhan_totp.is_auto_renew_enabled(root)),
            "days_left": None if days_left is None else round(float(days_left), 1),
            "policy_days": int(days_policy),
            "secret_marked": configured.strftime("%d-%b-%Y %H:%M IST") if configured else "",
            "last_refresh": last.strftime("%d-%b %H:%M IST") if last else "never",
            "last_ok": meta.get("last_refresh_ok"),
            "last_error": (str(meta.get("last_error") or "")[:160] or None),
        }
    except Exception:
        pass

    if not tok:
        dhan = {
            "present": False,
            "status": "None",
            "health_class": "none",
            "age_hours": 0.0,
            "expires_in_hours": 0.0,
            "jwt_exp": "N/A",
            "saved_at": "",
            "progress_pct": 0,
            "last4": "",
            "expires_at": "N/A",
        }
    else:
        age_h = ts.token_age_hours() or 0.0
        expires_in = ts.effective_expires_in_hours()
        if expires_in is None:
            expires_in = max(0.0, 24.0 - age_h)
        saved_fmt = saved_at.strftime("%d-%b %H:%M") if saved_at else "unknown"
        jwt_exp = ts.jwt_expires_at_local()
        jwt_line = jwt_exp.strftime("%d-%b %H:%M %Z") if jwt_exp else "N/A"
        if expires_in > 12:
            status, klass = "Healthy", "healthy"
        elif expires_in > 4:
            status, klass = "Expiring Soon", "soon"
        elif expires_in > 0:
            status, klass = "Critical", "critical"
        else:
            status, klass = "Expired", "expired"
        dhan = {
            "present": True,
            "status": status,
            "health_class": klass,
            "age_hours": round(float(age_h), 1),
            "expires_in_hours": round(float(expires_in), 1),
            "jwt_exp": jwt_line,
            "expires_at": jwt_line,
            "saved_at": f"{saved_fmt} IST",
            "progress_pct": min(100, int((expires_in / 24.0) * 100)),
            "last4": tok[-4:] if len(tok) >= 4 else "",
        }

    try:
        from core.order_broker_select import get_main_order_broker
        main_broker = get_main_order_broker(root)
    except Exception:
        main_broker = "zerodha"
    return {
        "dhan": dhan,
        "totp": totp,
        "zerodha": _zerodha_spot(root=root),
        "nifty": _nifty_spot(),
        "main_broker": main_broker,
    }


async def refresh_jwt_via_totp(
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    *,
    reply_markup: Any = None,
) -> None:
    from core import dhan_totp

    root = _root(context)
    await message.reply_text("⏳ Refreshing JWT via TOTP…", parse_mode=ParseMode.HTML)
    try:
        token = await asyncio.to_thread(dhan_totp.renew_and_save, root)
        persist_dhan_jwt(token, root=root, source="kavach2_totp")
    except Exception as exc:
        logger.error("Kavach TOTP refresh failed: %s", exc)
        await message.reply_text(
            "🔴 <b>JWT refresh failed</b>\n\n"
            f"<code>{html.escape(str(exc))}</code>\n\n"
            "Check <code>DHAN_PIN</code> / <code>DHAN_TOTP_SECRET</code> in "
            "<code>Credentials/config/.env</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return
    client_code = resolve_client_code(context)
    apply_token_runtime(context, token, client_code)
    store = token_store(root)
    await message.reply_text(
        "✅ <b>JWT refreshed via TOTP</b>\n\n" + token_summary(store, root=root),
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


async def process_pasted_token(
    update: Update,
    token: str,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    reply_markup: Any = None,
) -> None:
    from core.exceptions import BrokerAuthError, BrokerConnectionError
    from core.nifty_ltp import fetch_nifty_ltp, validate_dhan_access_token

    set_awaiting_token(context, False)
    if update.message is None:
        raise ValueError("Telegram update is missing a message")
    message: Message = update.message
    root = _root(context)
    client_code = resolve_client_code(context)

    await message.reply_text(
        "⏳ Validating Dhan token…",
        parse_mode=ParseMode.HTML,
    )
    if not client_code:
        await message.reply_text(
            "🔴 <b>Setup incomplete</b>\n\n"
            "Add <code>DHAN_CLIENT_CODE</code> to <code>Credentials/config/.env</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return

    ok, auth_error = await asyncio.to_thread(validate_dhan_access_token, client_code, token)
    if not ok:
        await message.reply_text(
            "🔴 <b>Token rejected by Dhan</b>\n\n"
            f"<code>{html.escape(auth_error)}</code>\n\n"
            "Nothing was saved. Paste a fresh JWT from Dhan web.",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return

    try:
        ltp, source = await fetch_nifty_ltp(client_code, token)
    except (BrokerAuthError, BrokerConnectionError) as exc:
        logger.error("Kavach token validation LTP failed: %s", exc)
        await message.reply_text(
            "🔴 <b>Token not saved</b>\n\n"
            f"<code>{html.escape(str(exc))}</code>\n\n"
            "Fix Dhan Data API subscription or paste a fresh JWT.",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return

    persist_dhan_jwt(token, root=root, source="kavach2_telegram")
    broker_connected = apply_token_runtime(context, token, client_code)
    verify = (
        "✅ <b>Dhan token saved for Kavach and Feeder</b>\n\n"
        f"NIFTY check: <b>₹{ltp:,.2f}</b> ({html.escape(str(source))})"
    )
    if not broker_connected:
        verify += (
            "\n\n⚠️ <b>Broker reconnect pending</b>\n"
            "Token is on disk. Tap MENU if broker stays disconnected."
        )
    await message.reply_text(verify, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
