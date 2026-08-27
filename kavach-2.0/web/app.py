"""Starlette control API + static Kavach desk."""

from __future__ import annotations

import re

import asyncio
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
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
        return _err(exc)


async def index(request: Request) -> Response:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = re.sub(
        r'app\.(css|js)\?v=[^"]+',
        lambda m: f'app.{m.group(1)}?v=20260827pos1',
        html,
    )
    return Response(html, media_type="text/html")


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
    return JSONResponse({"ok": True, "auth": True})


async def api_state(request: Request) -> Response:
    if not _authed(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    return JSONResponse(snapshot())


async def ws_state(ws: WebSocket) -> None:
    secret, _ = _secret_pw()
    cookie = ws.cookies.get(web_auth.COOKIE)
    if not web_auth.valid_session(secret, cookie):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            await ws.send_json(snapshot())
            await asyncio.sleep(1.5)
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


async def api_zerodha(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    body = await _read_json(request)
    return _cmd(commands.token_zerodha, str(body.get("token") or ""))


async def api_register(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        return _cmd(commands.register_defaults)
    body = await _read_json(request)
    return _cmd(commands.register_batman, body)


async def api_deploy(request: Request) -> Response:
    bad = _need_auth(request)
    if bad:
        return bad
    if request.method == "GET":
        return _cmd(commands.deploy_defaults)
    body = await _read_json(request)
    if body.get("preview") and not body.get("confirm"):
        return _cmd(commands.deploy_preview, body)
    return _cmd(commands.deploy_batman, body)


def create_app() -> Starlette:
    routes = [
        Route("/", index),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/me", api_me),
        Route("/api/state", api_state),
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
        Route("/api/token/zerodha", api_zerodha, methods=["POST"]),
        Route("/api/register", api_register, methods=["GET", "POST"]),
        Route("/api/deploy", api_deploy, methods=["GET", "POST"]),
        WebSocketRoute("/ws/state", ws_state),
        Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
    ]
    return Starlette(routes=routes)
