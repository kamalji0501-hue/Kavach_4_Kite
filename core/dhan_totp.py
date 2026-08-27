"""Shared Dhan TOTP auth — auto-generate JWT from PIN + TOTP secret.

Used by DRISHTI (and compatible with GO meta). Access tokens remain ~24h.
TOTP secret is long-lived in Credentials/config/.env; countdown/meta live in
shared dhan_totp_meta.json (falls back to legacy go_totp_meta.json).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx
import pyotp
from dotenv import load_dotenv

from core.batman_mode import access_token_path, secrets_dhan_env_path, shared_data_dir
from core.token_store import TokenStore

logger = logging.getLogger("batman.dhan.totp")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_GENERATE_URL = "https://auth.dhan.co/app/generateAccessToken"
_DEFAULT_POLICY_DAYS = 30
# Refresh when JWT effective remaining hours drop below this.
_REFRESH_WHEN_HOURS_LEFT = 4.0
_POLL_SECONDS = 300.0  # check every 5 minutes


def _meta_path(root: Path | None = None) -> Path:
    return shared_data_dir(root) / "dhan_totp_meta.json"


def _legacy_go_meta_path(root: Path | None = None) -> Path:
    return shared_data_dir(root) / "go_totp_meta.json"


def _load_env(root: Path | None = None) -> None:
    """Load Dhan secrets from config/.env then config/dhan.env.

    GO stores PIN/TOTP in ``.env``. Rahul layout also uses ``dhan.env``.
    Load both so either layout works; ``dhan.env`` only fills missing keys.
    """
    from core.batman_mode import secrets_root

    primary = secrets_dhan_env_path(root)
    if primary.is_file():
        load_dotenv(primary, override=False)
    dhan_env = secrets_root(root) / "config" / "dhan.env"
    if dhan_env.is_file():
        load_dotenv(dhan_env, override=False)
    if not primary.is_file() and not dhan_env.is_file():
        load_dotenv(override=False)


def policy_days(root: Path | None = None) -> int:
    _load_env(root)
    raw = os.environ.get("GO_TOTP_SECRET_MAX_DAYS", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    meta = load_meta(root)
    try:
        return max(1, int(meta.get("policy_days") or _DEFAULT_POLICY_DAYS))
    except (TypeError, ValueError):
        return _DEFAULT_POLICY_DAYS


@dataclass(frozen=True)
class TotpCredentials:
    client_code: str
    pin: str
    totp_secret: str

    @property
    def configured(self) -> bool:
        return bool(self.client_code and self.pin and self.totp_secret)


def load_credentials(root: Path | None = None) -> TotpCredentials:
    _load_env(root)
    return TotpCredentials(
        client_code=os.environ.get("DHAN_CLIENT_CODE", "").strip(),
        pin=os.environ.get("DHAN_PIN", "").strip(),
        totp_secret=os.environ.get("DHAN_TOTP_SECRET", "").strip().replace(" ", ""),
    )


def load_meta(root: Path | None = None) -> dict[str, Any]:
    """Load TOTP meta; prefer dhan_totp_meta.json, else legacy go_totp_meta.json."""
    for path in (_meta_path(root), _legacy_go_meta_path(root)):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def save_meta(meta: dict[str, Any], root: Path | None = None) -> None:
    """Persist meta to dhan_totp_meta.json and mirror to go_totp_meta.json for GO."""
    payload = json.dumps(meta, indent=2, sort_keys=True) + "\n"
    for path in (_meta_path(root), _legacy_go_meta_path(root)):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)


def _parse_ist(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_IST)
        return dt.astimezone(_IST)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text[:10], fmt).replace(tzinfo=_IST)
            except ValueError:
                continue
    return None


def ensure_configured_at(root: Path | None = None) -> datetime | None:
    """Return / initialize TOTP secret 'configured_at' for the 30-day countdown."""
    _load_env(root)
    meta = load_meta(root)
    existing = _parse_ist(meta.get("totp_configured_at"))
    if existing is not None:
        return existing

    env_at = _parse_ist(os.environ.get("DHAN_TOTP_CONFIGURED_AT", "").strip())
    creds = load_credentials(root)
    if not creds.totp_secret and env_at is None:
        return None

    now = env_at or datetime.now(_IST)
    meta["totp_configured_at"] = now.isoformat()
    meta.setdefault("policy_days", policy_days(root))
    meta.setdefault("auto_renew_enabled", True)
    save_meta(meta, root)
    return now


def totp_days_remaining(root: Path | None = None) -> tuple[float | None, datetime | None, int]:
    """Return (days_left, configured_at, policy_days). days_left may be negative if overdue."""
    days = policy_days(root)
    configured = ensure_configured_at(root) if load_credentials(root).totp_secret else _parse_ist(
        load_meta(root).get("totp_configured_at")
    )
    if configured is None:
        return None, None, days
    elapsed = (datetime.now(_IST) - configured).total_seconds() / 86400.0
    return days - elapsed, configured, days


def current_totp_code(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def _friendly_dhan_auth_error(payload: Any, fallback: str = "") -> str:
    msg = ""
    if isinstance(payload, dict):
        msg = str(payload.get("message") or payload.get("error") or "").strip()
    if not msg:
        msg = (fallback or "").strip()
    low = msg.lower()
    if "2 minutes" in low or "once every" in low:
        return (
            "Dhan allows a new JWT only once every 2 minutes. "
            "Wait a bit, then tap REFRESH JWT again."
        )
    if "invalid totp" in low:
        return (
            "Invalid TOTP. Dhan already used this 30-second code "
            "(usually because GO on the other server refreshed at the same time). "
            "Wait 30 seconds, then tap REFRESH JWT again. "
            "JWT refresh should run only on Kavach."
        )
    return msg or "Dhan JWT mint failed."


def generate_access_token(
    client_code: str,
    pin: str,
    totp_code: str,
    *,
    timeout: float = 30.0,
) -> str:
    """Call Dhan generateAccessToken; return JWT string.

    PIN and TOTP are sent as form fields so they never appear in httpx URL logs.
    """
    form = {
        "dhanClientId": client_code,
        "pin": pin,
        "totp": totp_code,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(_GENERATE_URL, data=form)
    payload: Any = None
    try:
        payload = resp.json()
    except Exception:
        payload = None
    if resp.status_code >= 400:
        snippet = (resp.text or "").strip()[:180]
        raise RuntimeError(_friendly_dhan_auth_error(payload, snippet or f"HTTP {resp.status_code}"))
    if not isinstance(payload, dict):
        raise RuntimeError("Dhan generateAccessToken returned invalid JSON")

    token = payload.get("accessToken") or payload.get("access_token")
    data = payload.get("data")
    if not token and isinstance(data, dict):
        token = data.get("accessToken") or data.get("access_token")
    if not token or not isinstance(token, str):
        raise RuntimeError(_friendly_dhan_auth_error(payload, "missing accessToken"))
    return token.strip()


def renew_and_save(root: Path | None = None) -> str:
    """Generate a fresh JWT via TOTP and persist to TokenStore. Updates meta."""
    creds = load_credentials(root)
    if not creds.configured:
        raise RuntimeError(
            "TOTP not configured — set DHAN_CLIENT_CODE, DHAN_PIN, DHAN_TOTP_SECRET "
            "in Credentials/config/.env"
        )

    code = current_totp_code(creds.totp_secret)
    token = generate_access_token(creds.client_code, creds.pin, code)
    from core.token_fanout import persist_dhan_jwt

    persist_dhan_jwt(token, root=root, source="kavach2_totp")

    meta = load_meta(root)
    now = datetime.now(_IST)
    if not meta.get("totp_configured_at"):
        env_at = _parse_ist(os.environ.get("DHAN_TOTP_CONFIGURED_AT", "").strip())
        meta["totp_configured_at"] = (env_at or now).isoformat()
    meta["policy_days"] = policy_days(root)
    meta["auto_renew_enabled"] = True
    meta["last_refresh_at"] = now.isoformat()
    meta["last_refresh_ok"] = True
    meta["last_error"] = None
    save_meta(meta, root)
    logger.info("Dhan TOTP: JWT renewed and saved to TokenStore")
    return token


def set_auto_renew_enabled(enabled: bool, root: Path | None = None) -> None:
    meta = load_meta(root)
    meta["auto_renew_enabled"] = bool(enabled)
    save_meta(meta, root)


def is_auto_renew_enabled(root: Path | None = None) -> bool:
    meta = load_meta(root)
    if "auto_renew_enabled" not in meta:
        return True
    return bool(meta.get("auto_renew_enabled"))


def needs_refresh(root: Path | None = None) -> bool:
    store = TokenStore(path=access_token_path(root))
    token, _ = store.load()
    if not token:
        return True
    if store.is_effectively_expired():
        return True
    hours = store.effective_expires_in_hours()
    if hours is None:
        return store.is_expired()
    return hours <= _REFRESH_WHEN_HOURS_LEFT


def status_html(root: Path | None = None) -> str:
    """TOTP credential + 30-day countdown block for Telegram."""
    creds = load_credentials(root)
    days_left, configured, days_policy = totp_days_remaining(root)
    meta = load_meta(root)
    auto = is_auto_renew_enabled(root)

    if not creds.configured:
        missing = []
        if not creds.client_code:
            missing.append("DHAN_CLIENT_CODE")
        if not creds.pin:
            missing.append("DHAN_PIN")
        if not creds.totp_secret:
            missing.append("DHAN_TOTP_SECRET")
        return (
            "🔐 <b>TOTP Auto-Login</b>\n"
            "🔴 <b>Not configured</b>\n\n"
            f"Add to <code>Credentials/config/.env</code>:\n"
            f"<code>{', '.join(missing)}</code>\n\n"
            "Then tap <b>Token Status → REFRESH JWT</b>."
        )

    if days_left is None:
        due_line = "📅 <b>Secret refresh:</b> countdown starts after first successful refresh"
    elif days_left > 7:
        due_line = f"🟢 <b>TOTP secret refresh due in:</b> {days_left:.1f} days"
    elif days_left > 0:
        due_line = f"🟡 <b>TOTP secret refresh due in:</b> {days_left:.1f} days"
    else:
        due_line = (
            f"🔴 <b>TOTP secret overdue by:</b> {abs(days_left):.1f} days "
            f"— update <code>DHAN_TOTP_SECRET</code> in .env"
        )

    configured_fmt = (
        configured.strftime("%d-%b-%Y %H:%M IST") if configured else "—"
    )
    last = _parse_ist(meta.get("last_refresh_at"))
    last_fmt = last.strftime("%d-%b %H:%M IST") if last else "never"
    last_ok = meta.get("last_refresh_ok")
    last_icon = "✅" if last_ok else ("⚠️" if last_ok is False else "—")
    err = meta.get("last_error")
    err_line = (
        f"\n⚠️ <b>Last error:</b> <code>{str(err)[:160]}</code>" if err else ""
    )

    return (
        "🔐 <b>TOTP Auto-Login</b>\n"
        f"{'🟢' if auto else '⏸'} <b>Auto-renew:</b> {'ON' if auto else 'OFF'}\n"
        f"{due_line}\n"
        f"📆 <b>Policy:</b> {days_policy} days\n"
        f"📅 <b>Secret marked:</b> {configured_fmt}\n"
        f"{last_icon} <b>Last JWT refresh:</b> {last_fmt}"
        f"{err_line}"
    )


class TotpRenewer:
    """Background thread: keep TokenStore JWT fresh via TOTP."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        on_token: Callable[[str], None] | None = None,
        poll_seconds: float = _POLL_SECONDS,
    ) -> None:
        self.root = root
        self.on_token = on_token
        self.poll_seconds = float(poll_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="dhan-totp-renewer", daemon=True
        )
        self._thread.start()
        logger.info("Dhan TOTP renewer started (poll=%.0fs)", self.poll_seconds)

    def stop(self) -> None:
        self._stop.set()

    def refresh_now(self) -> str:
        with self._lock:
            token = renew_and_save(self.root)
            if self.on_token is not None:
                self.on_token(token)
            return token

    def _loop(self) -> None:
        # Short initial delay so Telegram app finishes bootstrapping.
        self._stop.wait(5.0)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.exception("Dhan TOTP renewer tick failed: %s", exc)
                meta = load_meta(self.root)
                meta["last_refresh_ok"] = False
                meta["last_error"] = str(exc)[:300]
                meta["last_refresh_at"] = datetime.now(_IST).isoformat()
                save_meta(meta, self.root)
            self._stop.wait(self.poll_seconds)

    def _tick(self) -> None:
        if not load_credentials(self.root).configured:
            return
        if not is_auto_renew_enabled(self.root):
            return
        if not needs_refresh(self.root):
            return
        logger.info("Dhan TOTP: JWT needs refresh — generating via TOTP")
        with self._lock:
            token = renew_and_save(self.root)
            if self.on_token is not None:
                try:
                    self.on_token(token)
                except Exception as exc:
                    logger.error("Dhan TOTP on_token callback failed: %s", exc)
