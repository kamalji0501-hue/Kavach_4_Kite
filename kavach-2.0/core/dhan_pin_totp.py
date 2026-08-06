"""
Dhan PIN + TOTP authentication helpers (Tradehull ``mode="pin_totp"``).

Ported from Fetch Historical Data auth pattern:
  Tradehull(client_id, mode="pin_totp", pin=..., totp_secret=...)

Secrets are read from **environment only** (after optional load_dotenv of the
runtime secrets path). Never commit PIN / TOTP seed. Never write PIN or TOTP
seed to disk from this module — only the resulting daily JWT may be saved via
``TokenStore`` by callers.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("batman.dhan_pin_totp")


@dataclass(frozen=True)
class DhanPinTotpCredentials:
    """Broker login material for PIN/TOTP (repr hides secrets)."""

    client_code: str
    pin: str = field(repr=False)
    totp_secret: str = field(repr=False)


def _env(*names: str) -> str:
    for name in names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return ""


def ensure_dhan_secrets_loaded(root=None) -> None:
    """Load desktop/runtime Dhan secrets into env (no-op if already set)."""
    try:
        from core.dhan_credentials import apply_dhan_secrets_env

        apply_dhan_secrets_env(root)
    except Exception:
        pass


def pin_totp_env_present(root=None) -> bool:
    """True when PIN and TOTP seed are available (after secrets_root load)."""
    ensure_dhan_secrets_loaded(root)
    return bool(_env("DHAN_PIN", "FTLTP_PIN") and _env("DHAN_TOTP_SECRET", "FTLTP_TOTP_SECRET"))


def load_pin_totp_credentials_from_env(*, require: bool = False) -> DhanPinTotpCredentials | None:
    """Load client code + PIN + TOTP seed from env.

    Client code aliases: ``DHAN_CLIENT_CODE``, ``DHAN_CLIENT_ID``, ``FTLTP_CLIENT_ID``.
    PIN: ``DHAN_PIN`` / ``FTLTP_PIN``.
    TOTP seed (Base32): ``DHAN_TOTP_SECRET`` / ``FTLTP_TOTP_SECRET`` — not a 6-digit OTP.
    """
    ensure_dhan_secrets_loaded()
    client_code = _env("DHAN_CLIENT_CODE", "DHAN_CLIENT_ID", "FTLTP_CLIENT_ID")
    pin = _env("DHAN_PIN", "FTLTP_PIN")
    totp_secret = _env("DHAN_TOTP_SECRET", "FTLTP_TOTP_SECRET")

    if not pin or not totp_secret:
        if require:
            raise ValueError(
                "Dhan PIN/TOTP auth requires DHAN_PIN and DHAN_TOTP_SECRET "
                "(Base32 seed, not a 6-digit code). Do not commit these values."
            )
        return None
    if not client_code:
        if require:
            raise ValueError(
                "Dhan PIN/TOTP auth requires DHAN_CLIENT_CODE (or DHAN_CLIENT_ID)."
            )
        return None
    return DhanPinTotpCredentials(
        client_code=client_code,
        pin=pin,
        totp_secret=totp_secret,
    )


def login_tradehull_pin_totp(creds: DhanPinTotpCredentials) -> Any:
    """Create a Tradehull session via ``pin_totp`` (same as Fetch Historical Data)."""
    try:
        from Dhan_Tradehull import Tradehull
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Dhan-Tradehull not installed. Run: pip install Dhan-Tradehull"
        ) from exc

    logger.info("Dhan login via PIN/TOTP (Tradehull pin_totp) for client=%s", creds.client_code)
    try:
        tsl = Tradehull(
            ClientCode=creds.client_code,
            mode="pin_totp",
            pin=creds.pin,
            totp_secret=creds.totp_secret,
        )
    except Exception as exc:
        raise RuntimeError(
            "Dhan/Tradehull PIN/TOTP login failed. "
            "Check DHAN_PIN, DHAN_TOTP_SECRET, and system clock sync."
        ) from exc

    if not hasattr(tsl, "instrument_df"):
        raise RuntimeError(
            "Tradehull PIN/TOTP login did not load instrument master (missing instrument_df)."
        )
    return tsl


def extract_access_token(tsl: Any) -> str:
    """Return the JWT Tradehull stored on the session after login."""
    token = (getattr(tsl, "token_id", None) or getattr(tsl, "access_token", None) or "").strip()
    if not token:
        raise RuntimeError("Tradehull PIN/TOTP login succeeded but no access token was exposed.")
    return token


def obtain_access_token_via_pin_totp(
    creds: DhanPinTotpCredentials | None = None,
) -> tuple[str, str]:
    """Login with PIN/TOTP and return ``(client_code, access_token)``.

    Does not persist PIN or TOTP. Caller may save the JWT to TokenStore.
    """
    if creds is None:
        creds = load_pin_totp_credentials_from_env(require=True)
        assert creds is not None
    tsl = login_tradehull_pin_totp(creds)
    token = extract_access_token(tsl)
    # Never log token / pin / totp
    logger.info(
        "PIN/TOTP obtained daily JWT (len=%s) for client=%s",
        len(token),
        creds.client_code,
    )
    return creds.client_code, token
