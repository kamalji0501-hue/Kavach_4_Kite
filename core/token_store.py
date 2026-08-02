"""
Batman v3 — Dhan access-token persistence.

Saves the Dhan JWT access token (and its load timestamp) to a local JSON
file so that on a VPS restart Batman can reconnect immediately — without
waiting for Rahul to manually send the token to DRISHTI again.

File location:  data/access_token.json
Format::

    {
        "access_token": "<jwt>",
        "saved_at":     "2026-04-09T09:35:12"   ← ISO-format, no tz
    }

Usage::

    store = TokenStore(path=Path("data/access_token.json"))
    store.save(access_token)            # called by DRISHTI after hot_reload_token()
    token, saved_at = store.load()      # called by main.py at startup
    if token and not store.is_expired():
        broker = BatmanBroker.connect_with_token(client_code, token)
    else:
        # Token absent or older than 24h — wait for DRISHTI
        ...

Security note:  The token file is stored locally on the VPS and should
NOT be committed to git.  Add ``data/access_token.json`` to .gitignore.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.process_lock import exclusive_file_lock

logger = logging.getLogger("batman.token_store")

_TOKEN_TTL_HOURS = 24  # Dhan access tokens are valid for exactly 24 hours


def jwt_expires_at(token: str) -> datetime | None:
    """Return JWT ``exp`` claim as timezone-aware UTC, or None if unreadable."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp")
        if exp is None:
            return None
        return datetime.fromtimestamp(int(exp), tz=UTC)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def jwt_expires_in_hours(token: str, *, now: datetime | None = None) -> float | None:
    exp = jwt_expires_at(token)
    if exp is None:
        return None
    now = now or datetime.now(UTC)
    return (exp - now).total_seconds() / 3600.0


class TokenStore:
    """Thin wrapper around ``data/access_token.json``.

    Thread-safe reads/writes via atomic file replace.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else Path("data") / "access_token.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(self, access_token: str) -> None:
        """Persist *access_token* with the current timestamp."""
        payload = {
            "access_token": access_token,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            tmp = self._path.with_suffix(".tmp")
            with exclusive_file_lock(self._path, timeout=5.0):
                tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                tmp.replace(self._path)
        logger.info("Access token saved → %s (saved_at=%s)", self._path, payload["saved_at"])

    # ── Read ─────────────────────────────────────────────────────────────────

    def load(self) -> tuple[str | None, datetime | None]:
        """Return ``(access_token, saved_at)`` or ``(None, None)`` if not found."""
        with self._lock:
            if not self._path.exists():
                return None, None
            try:
                with exclusive_file_lock(self._path, timeout=5.0):
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                token = data.get("access_token") or None
                saved_at = datetime.fromisoformat(data["saved_at"]) if "saved_at" in data else None
                return token, saved_at
            except Exception as exc:
                logger.warning("Token store read failed (%s) — treating as absent", exc)
                return None, None

    def is_expired(self, extra_tolerance_hours: float = 0.0) -> bool:
        """True if the stored token is older than (TTL − tolerance)."""
        _, saved_at = self.load()
        if saved_at is None:
            return True  # no token = treat as expired
        age = datetime.now() - saved_at
        limit = timedelta(hours=_TOKEN_TTL_HOURS - extra_tolerance_hours)
        return age >= limit

    def is_effectively_expired(self, extra_tolerance_hours: float = 0.0) -> bool:
        """True when save-age TTL or JWT ``exp`` has elapsed (conservative)."""
        eff = self.effective_expires_in_hours()
        if eff is None:
            return True
        return eff <= float(extra_tolerance_hours)

    def token_age_hours(self) -> float | None:
        """Hours since the stored token was saved, or None if absent."""
        _, saved_at = self.load()
        if saved_at is None:
            return None
        return (datetime.now() - saved_at).total_seconds() / 3600

    def save_based_expires_in_hours(self) -> float | None:
        """Hours until 24h window from ``saved_at`` expires."""
        age_h = self.token_age_hours()
        if age_h is None:
            return None
        return max(0.0, float(_TOKEN_TTL_HOURS) - age_h)

    def jwt_expires_in_hours(self) -> float | None:
        tok, _ = self.load()
        if not tok:
            return None
        return jwt_expires_in_hours(tok)

    def effective_expires_in_hours(self) -> float | None:
        """Conservative expiry: sooner of save-age TTL and JWT ``exp``."""
        save_h = self.save_based_expires_in_hours()
        jwt_h = self.jwt_expires_in_hours()
        if save_h is None and jwt_h is None:
            return None
        if save_h is None:
            return jwt_h
        if jwt_h is None:
            return save_h
        return min(save_h, jwt_h)

    def jwt_expires_at_local(self) -> datetime | None:
        tok, _ = self.load()
        if not tok:
            return None
        exp = jwt_expires_at(tok)
        if exp is None:
            return None
        return exp.astimezone()

    def clear(self) -> None:
        """Delete the stored token file (e.g. on explicit revoke)."""
        with self._lock:
            if self._path.exists():
                with exclusive_file_lock(self._path, timeout=5.0):
                    if self._path.exists():
                        self._path.unlink()
                logger.info("Token store cleared")
