"""Session cookie auth for the Kavach web desk."""

from __future__ import annotations

import hmac
import os
import secrets
import time
from hashlib import sha256
from pathlib import Path

from dotenv import load_dotenv

COOKIE = "kavach_web"
TTL_S = 12 * 3600


def _runtime_root() -> Path:
    env = os.environ.get("TRADING_RUNTIME", "").strip()
    if env:
        return Path(env)
    return Path("/home/ubuntu/Trading_Runtime_Rahul")


def web_env_path() -> Path:
    return _runtime_root() / "Credentials" / "web" / "kavach_web.env"


def ensure_web_secrets() -> tuple[str, str]:
    path = web_env_path()
    if path.is_file():
        load_dotenv(path, override=True)
    password = os.environ.get("KAVACH_WEB_PASSWORD", "").strip()
    secret = os.environ.get("KAVACH_WEB_SESSION_SECRET", "").strip()
    changed = False
    if not password:
        password = secrets.token_urlsafe(16)
        os.environ["KAVACH_WEB_PASSWORD"] = password
        changed = True
    if not secret:
        secret = secrets.token_hex(32)
        os.environ["KAVACH_WEB_SESSION_SECRET"] = secret
        changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"KAVACH_WEB_PASSWORD={password}\n"
            f"KAVACH_WEB_SESSION_SECRET={secret}\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o600)
    return password, secret


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), sha256).hexdigest()


def make_session(secret: str) -> str:
    payload = str(int(time.time()))
    return f"{payload}.{_sign(secret, payload)}"


def valid_session(secret: str, cookie: str | None) -> bool:
    if not cookie or "." not in cookie:
        return False
    payload, sig = cookie.split(".", 1)
    if not hmac.compare_digest(sig, _sign(secret, payload)):
        return False
    try:
        ts = int(payload)
    except ValueError:
        return False
    return 0 <= time.time() - ts < TTL_S


def password_ok(expected: str, given: str) -> bool:
    return hmac.compare_digest(expected.encode(), (given or "").encode())
