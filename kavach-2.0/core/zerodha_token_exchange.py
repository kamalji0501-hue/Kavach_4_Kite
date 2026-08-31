"""Resolve Kite login URL / request_token / access_token to a valid access_token."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

logger = logging.getLogger("batman.zerodha.exchange")

_REQUEST_RE = re.compile(r"request_token=([A-Za-z0-9]+)")


def _candidate_env_paths() -> list[Path]:
    return [
        Path("/home/ubuntu/Datafeedbot_Runtime/Credentials/zerodha/zerodha.env"),
        Path("/home/ubuntu/Trading_Runtime_Rahul/Credentials/zerodha/zerodha.env"),
        Path("/home/ubuntu/rahul_Changes/kavach-2.0/config/zerodha.env"),
    ]


def load_api_credentials() -> tuple[str, str, str]:
    """Return (api_key, api_secret, user_id)."""
    for path in _candidate_env_paths():
        if path.is_file():
            load_dotenv(path, override=True)
            break
    api_key = (
        os.environ.get("ZERODHA_API_KEY", "").strip()
        or os.environ.get("KITE_API_KEY", "").strip()
    )
    api_secret = (
        os.environ.get("ZERODHA_API_SECRET", "").strip()
        or os.environ.get("KITE_API_SECRET", "").strip()
    )
    user_id = (
        os.environ.get("ZERODHA_USER_ID", "").strip()
        or os.environ.get("KITE_USER_ID", "").strip()
    )
    return api_key, api_secret, user_id


def extract_request_token(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        vals = parse_qs(urlparse(raw).query).get("request_token") or []
        if vals:
            return str(vals[0]).strip()
    except Exception:
        pass
    m = _REQUEST_RE.search(raw)
    return m.group(1) if m else None


def validate_access_token(api_key: str, access_token: str) -> tuple[bool, str]:
    if not api_key or not access_token:
        return False, "missing api_key or access_token"
    try:
        from datafeedbot.auth.zerodha_token import validate_access_token as _validate

        profile = _validate(api_key, access_token)
        if profile:
            uid = str(profile.get("user_id") or profile.get("user_name") or "ok")
            return True, uid
    except Exception as exc:
        logger.debug("validate_access_token import/call failed: %s", exc)
    try:
        import httpx

        r = httpx.get(
            "https://api.kite.trade/user/profile",
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {api_key}:{access_token}",
            },
            timeout=15.0,
        )
        if r.status_code == 200:
            body = r.json()
            if body.get("status") == "success":
                data = body.get("data") or {}
                uid = str(data.get("user_id") or data.get("user_name") or "ok")
                return True, uid
        return False, "Kite rejected token (403/expired)"
    except Exception as exc:
        return False, str(exc)


def exchange_request_token(request_token: str, *, api_key: str, api_secret: str) -> dict[str, Any]:
    if not api_key or not api_secret:
        raise ValueError("Zerodha API key/secret missing in runtime credentials")
    rt = (request_token or "").strip()
    if not rt:
        raise ValueError("empty request_token")

    import hashlib

    import httpx

    checksum = hashlib.sha256(f"{api_key}{rt}{api_secret}".encode()).hexdigest()
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(
            "https://api.kite.trade/session/token",
            data={
                "api_key": api_key,
                "request_token": rt,
                "checksum": checksum,
            },
            headers={"X-Kite-Version": "3"},
        )
    try:
        body = resp.json()
    except Exception as exc:
        raise ValueError(f"Kite session/token HTTP {resp.status_code}: {resp.text[:200]}") from exc
    if resp.status_code != 200 or body.get("status") != "success":
        msg = body.get("message") or resp.text[:200]
        raise ValueError(f"Kite session/token failed: {msg}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise ValueError("Kite session/token returned unexpected payload")
    access = str(data.get("access_token") or "").strip()
    if not access:
        raise ValueError("Kite session/token returned empty access_token")
    return data


def resolve_kite_access_token(raw: str) -> tuple[str, str]:
    """Return (access_token, detail). Raises ValueError on failure."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty token input")

    api_key, api_secret, _user_id = load_api_credentials()
    if not api_key:
        raise ValueError("ZERODHA_API_KEY not configured on VPS")

    request_token = extract_request_token(text)
    if request_token:
        try:
            data = exchange_request_token(request_token, api_key=api_key, api_secret=api_secret)
        except Exception as exc:
            raise ValueError(
                f"Could not exchange request_token (one-time, expires in minutes): {exc}"
            ) from exc
        access = str(data.get("access_token") or "").strip()
        uid = str(data.get("user_id") or "ok")
        ok, reason = validate_access_token(api_key, access)
        if not ok:
            raise ValueError(f"Exchanged token still rejected: {reason}")
        return access, uid

    candidate = text
    ok, reason = validate_access_token(api_key, candidate)
    if ok:
        return candidate, reason

    if api_secret and re.fullmatch(r"[A-Za-z0-9]{20,64}", candidate):
        try:
            data = exchange_request_token(candidate, api_key=api_key, api_secret=api_secret)
            access = str(data.get("access_token") or "").strip()
            ok2, reason2 = validate_access_token(api_key, access)
            if ok2:
                return access, str(data.get("user_id") or reason2)
        except Exception:
            pass

    raise ValueError(
        "Not a valid Kite access_token. Paste the full login redirect URL "
        "(with request_token=...) right after Kite login, or paste a fresh access_token."
    )
