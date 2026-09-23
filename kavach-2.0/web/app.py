"""Starlette control API + static Kavach desk."""

from __future__ import annotations

import re

import asyncio
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from web import auth as web_auth
from web import commands
from web.runtime import get_runtime
from web.state import snapshot

logger = logging.getLogger("batman.kavach.web")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _secret_pw() -> tuple[str, str]:
    path = web_auth.web_env_path()
    if path.is_file():
        from dotenv import load_dotenv
        import os

        load_dotenv(path, override=True)
        pw = os.environ.get("KAVACH_WEB_PASSWORD", "").strip()
        sec = os.environ.get("KAVACH_WEB_SESSION_SECRET", "").strip()
        if pw and sec:
            rt = get_runtime()
            if rt is not None:
                rt.web_password = pw
                rt.session_secret = sec
            return sec, pw
    rt = get_runtime()
    if rt and rt.session_secret and rt.web_password:
        return rt.session_secret, rt.web_password
    return web_auth.ensure_web_secrets()


def _authed(request: Request) -> bool:
    secret, _ = _secret_pw()
    return web_auth.valid_session(secret, request.cookies.get(web_auth.COOKIE))


async def _read_json(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _err(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)


def _cmd(fn, *args, **kwargs) -> JSONResponse:
    try:
        data = fn(*args, **kwargs)
        if data is None:
            return JSONResponse({"ok": True})
        if isinstance(data, dict) and "ok" in data:
            return JSONResponse(data)
        return JSONResponse({"ok": True, "data": data})
    except Exception as exc:
        logger.warning("web command failed: %s", exc)
        try:
            from core.desk_alerts import emit_desk_alert

            msg = str(exc)
            low = msg.lower()
            if "2 minutes" in low or "jwt" in low:
                emit_desk_alert(
                    severity="orange",
                    category="Tokens",
                    alert="Dhan will not give a new login yet — wait 2 minutes and tap Refresh again.",
                    log=msg,
                )
            else:
                sev = "red" if any(k in low for k in ("halt", "reject", "blocked", "timeout", "mismatch")) else "orange"
                emit_desk_alert(severity=sev, category="Desk", alert=msg, log=msg)
        except Exception:
            pass
        return _err(exc)


async def index(request: Request) -> Response:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = re.sub(
        r'app\.(css|js)\?(?:v|cb)=[^"]+',
        lambda m: f'app.{m.group(1)}?cb=20260918posTitleTotal',
        html,
    )
    return Response(html, media_type="text/html")


async def pwa_manifest(request: Request) -> Response:
    return FileResponse(
        STATIC_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


async def pwa_sw(request: Request) -> Response:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="text/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


async def login(request: Request) -> Response:
    body = await _read_json(request)
    secret, password = _secret_pw()
    if not web_auth.password_ok(password, str(body.get("password") or "")):
        return JSONResponse({"ok": False, "error": "bad password"}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        web_auth.COOKIE,
        web_auth.make_session(secret),
        httponly=True,
        samesite="lax",
        max_age=web_auth.TTL_S,
        path="/",
    )
    return resp


async def logout(request: Request) -> Response:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(web_auth.COOKIE, path="/")
    return resp


async def api_me(request: Request) -> Response:
    if not _authed(request):
        return JSONResponse({"ok": False, "auth": False}, status_code=401)
    zerodha = {"user_id": "", "name": "", "present": False}
    dhan = {"client_id": "", "name": "", "present": False}
    try:
        from core.zerodha_account_label import get_zerodha_account_label

        zerodha = get_zerodha_account_label()
        if "present" not in zerodha:
            zerodha["present"] = bool(zerodha.get("user_id") or zerodha.get("name"))
    except Exception as exc:
        logger.warning("zerodha account label failed: %s", exc)
    try:
        import os

        from bat_telegram.bots.kavach2.token_ui import token_snapshot
        from web.runtime import get_runtime

        rt = get_runtime()
        snap = token_snapshot(root=rt.root if rt else None)
        ztok = (snap or {}).get("zerodha") or {}
        dtok = (snap or {}).get("dhan") or {}
        if ztok.get("present"):
            zerodha["present"] = True
        dhan = {
            "client_id": (os.environ.get("DHAN_CLIENT_CODE") or "").strip(),
            "name": "",
            "present": bool(dtok.get("present")),
        }
    except Exception as exc:
        logger.warning("dhan account label failed: %s", exc)
    return JSONResponse({"ok": True, "auth": True, "zerodha": zerodha, "dhan": dhan})



async def api_ato_readiness(request: Request) -> Response:
    if not _authed(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    try:
        from core.ato_readiness import ato_readiness_snapshot
        data = ato_readiness_snapshot()
        data["ok"] = True
        return JSONResponse(data)
    except Exception as exc:
        return _err(exc)


async def api_state(request: Request) -> Response:
    if not _authed(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    return JSONResponse(snapshot())


async def api_alerts(request: Request) -> Response:
    if not _authed(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    try:
        from core.desk_alerts import for_day

        raw = request.query_params.get("limit") or "200"
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            limit = 200
        rows = for_day(limit=limit)
        return JSONResponse({"ok": True, "alerts": rows})
    except Exception as exc:
        return _err(exc)


async def ws_state(ws: WebSocket) -> None:
    secret, _ = _secret_pw()
    cookie = ws.cookies.get(web_auth.COOKIE)
    if not web_auth.valid_session(secret, cookie):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            data = await asyncio.to_thread(snapshot)
            await ws.send_json(data)
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass


def _need_auth(request: Request) -> JSONResponse | None:
    if not _authed(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    return None


async def api_status(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.kavach_status)


async def api_ato_status(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.ato_status)


async def api_positions(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.ato_positions)


async def api_legs(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.core_legs)

async def api_trade_summary(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    from web.trade_summary import trade_summary

    return JSONResponse(trade_summary())



async def api_environment(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.environment)


async def api_pause(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.pause)


async def api_resume(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.resume)


async def api_dyn_hedge(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        return _cmd(commands.dyn_hedge_get)
    body = await _read_json(request)
    return _cmd(commands.dyn_hedge_set, bool(body.get("enabled")))


async def api_complete(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    body = await _read_json(request)
    return _cmd(commands.batman_complete, confirm=bool(body.get("confirm")))


async def api_buffer(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        return _cmd(commands.buffer_get)
    body = await _read_json(request)
    return _cmd(commands.buffer_set, body)


async def api_poll(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        return _cmd(commands.poll_get)
    body = await _read_json(request)
    return _cmd(commands.poll_set, body)


async def api_token_status(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.token_status)


async def api_token_refresh(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.token_refresh)


async def api_token_paste(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    body = await _read_json(request)
    return _cmd(commands.token_paste, str(body.get("token") or body.get("jwt") or ""))


async def api_token_off(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.token_deactivate)


async def api_main_broker(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        return _cmd(commands.token_main_broker_get)
    body = await _read_json(request)
    return _cmd(commands.token_main_broker_set, str(body.get("main_broker") or body.get("broker") or ""))


async def api_zerodha(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    body = await _read_json(request)
    return _cmd(commands.token_zerodha, str(body.get("token") or ""))


async def api_zerodha_off(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.token_zerodha_deactivate)


async def api_register(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        expiry = str(request.query_params.get("expiry") or "").strip()
        return _cmd(commands.register_defaults, expiry or None)
    body = await _read_json(request)
    return _cmd(commands.register_batman, body)


async def api_deploy(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        expiry = str(request.query_params.get("expiry") or "").strip()
        return _cmd(commands.deploy_defaults, expiry or None)
    body = await _read_json(request)
    if body.get("preview") and not body.get("confirm"):
        return _cmd(commands.deploy_preview, body)
    return _cmd(commands.deploy_batman, body)


async def api_deploy_register(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    body = await _read_json(request)
    return _cmd(commands.deploy_and_register_batman, body)




async def api_safe_exit(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    from core.pnl_exit_guard import set_safe_exit, snapshot_pnl_exit, current_day_pnl
    from web.runtime import require_runtime

    rt = require_runtime()
    if request.method == "GET":
        return JSONResponse(
            {
                "ok": True,
                "pnl_exit": snapshot_pnl_exit(rt.state),
                "day_pnl": current_day_pnl(),
            }
        )
    body = await request.json()
    on = bool(body.get("on"))
    level = body.get("level_rs", body.get("level"))
    try:
        level_f = None if level is None or level == "" else float(level)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "Safe Exit level must be a number."}, status_code=400)
    out = set_safe_exit(rt.state, on=on, level=level_f)
    code = 200 if out.get("ok") else 400
    return JSONResponse(out, status_code=code)


async def api_take_profit(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    from core.pnl_exit_guard import set_take_profit, snapshot_pnl_exit, current_day_pnl
    from web.runtime import require_runtime

    rt = require_runtime()
    if request.method == "GET":
        return JSONResponse(
            {
                "ok": True,
                "pnl_exit": snapshot_pnl_exit(rt.state),
                "day_pnl": current_day_pnl(),
            }
        )
    body = await request.json()
    on = bool(body.get("on"))
    level = body.get("level_rs", body.get("level"))
    try:
        level_f = None if level is None or level == "" else float(level)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "Take Profit level must be a number."}, status_code=400)
    out = set_take_profit(rt.state, on=on, level=level_f)
    code = 200 if out.get("ok") else 400
    return JSONResponse(out, status_code=code)



async def api_flatten(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    body = await _read_json(request)
    if not bool(body.get("confirm")):
        return JSONResponse(
            {
                "ok": False,
                "need_confirm": True,
                "error": "Confirm required to exit all positions.",
            },
            status_code=400,
        )
    from core.pnl_exit_guard import current_day_pnl, flatten_now, snapshot_pnl_exit
    from web.runtime import require_runtime

    rt = require_runtime()
    if rt.broker is None:
        return JSONResponse({"ok": False, "error": "Broker not available."}, status_code=400)
    out = flatten_now(
        broker=rt.broker,
        state=rt.state,
        events=rt.event_bus,
        reason="manual_exit",
    )
    out["pnl_exit"] = snapshot_pnl_exit(rt.state)
    out["day_pnl"] = current_day_pnl()
    code = 200 if out.get("ok") else 400
    return JSONResponse(out, status_code=code)


async def api_hedge_box(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        return _cmd(commands.hedge_box_status)
    body = await _read_json(request)
    if str(body.get("action") or "").strip().lower() == "deny":
        return _cmd(commands.hedge_box_deny)
    return JSONResponse({"ok": False, "error": "Unknown hedge-box action."}, status_code=400)


async def api_payoff(request: Request) -> Response:
    bad = _need_auth(request)
    return bad or _cmd(commands.payoff_graph)


def create_app() -> Starlette:
    routes = [
        Route("/", index),
        Route("/manifest.webmanifest", pwa_manifest),
        Route("/sw.js", pwa_sw),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/me", api_me),
        Route("/api/state", api_state),
        Route("/api/alerts", api_alerts),
        Route("/api/ato-readiness", api_ato_readiness),
        Route("/api/status", api_status),
        Route("/api/ato-status", api_ato_status),
        Route("/api/positions", api_positions),
        Route("/api/legs", api_legs),
        Route("/api/trade-summary", api_trade_summary),
        Route("/api/environment", api_environment),
        Route("/api/pause", api_pause, methods=["POST"]),
        Route("/api/resume", api_resume, methods=["POST"]),
        Route("/api/dyn-hedge", api_dyn_hedge, methods=["GET", "POST"]),
        Route("/api/complete", api_complete, methods=["POST"]),
        Route("/api/buffer", api_buffer, methods=["GET", "POST"]),
        Route("/api/poll", api_poll, methods=["GET", "POST"]),
        Route("/api/token/status", api_token_status),
        Route("/api/token/refresh", api_token_refresh, methods=["POST"]),
        Route("/api/token/dhan-jwt", api_token_paste, methods=["POST"]),
        Route("/api/token/deactivate", api_token_off, methods=["POST"]),
        Route("/api/token/main-broker", api_main_broker, methods=["GET", "POST"]),
        Route("/api/token/zerodha", api_zerodha, methods=["POST"]),
        Route("/api/token/zerodha/deactivate", api_zerodha_off, methods=["POST"]),
        Route("/api/register", api_register, methods=["GET", "POST"]),
        Route("/api/deploy", api_deploy, methods=["GET", "POST"]),
        Route("/api/deploy-register", api_deploy_register, methods=["POST"]),
        Route("/api/safe-exit", api_safe_exit, methods=["GET", "POST"]),
        Route("/api/take-profit", api_take_profit, methods=["GET", "POST"]),
        Route("/api/flatten", api_flatten, methods=["POST"]),
        Route("/api/hedge-box", api_hedge_box, methods=["GET", "POST"]),
        Route("/api/payoff", api_payoff),
        WebSocketRoute("/ws/state", ws_state),
        Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
    ]
    return Starlette(routes=routes)
