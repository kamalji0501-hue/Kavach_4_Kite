"""Dhan credentials on the user desktop / runtime secrets root.

Mirrors ``core.telegram_credentials``: code stays clean; secrets live outside git.

Preferred locations (checked in order)::

    <secrets_root>/config/dhan.env     # Dhan-only (recommended)
    <secrets_root>/config/.env         # legacy combined file (still supported)

On Rahul VPS, ``secrets_root`` is typically::

    /home/ubuntu/Trading_Runtime_Rahul/Credentials

On a Windows desktop default (when not overridden)::

    %USERPROFILE%\\Desktop\\Batman-Secrets

Expected keys (never commit real values)::

    DHAN_CLIENT_CODE=...
    DHAN_PIN=...
    DHAN_TOTP_SECRET=...          # Base32 seed, not 6-digit OTP
    DHAN_ACCESS_TOKEN=...         # optional manual JWT

PIN/TOTP enable automated daily JWT via Tradehull ``pin_totp``.
Telegram bot tokens stay in ``telegram/bots.env`` — not here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

_PLACEHOLDER_MARKERS = ("YOUR_", "PLACEHOLDER", "CHANGEME", "<ENTER", "PASTE")

DHAN_ENV_KEYS = (
    "DHAN_CLIENT_CODE",
    "DHAN_CLIENT_ID",
    "DHAN_PIN",
    "DHAN_TOTP_SECRET",
    "DHAN_ACCESS_TOKEN",
    "FTLTP_CLIENT_ID",
    "FTLTP_PIN",
    "FTLTP_TOTP_SECRET",
)


def is_placeholder(value: str | None) -> bool:
    if value is None or not str(value).strip():
        return True
    upper = str(value).upper()
    return any(m in upper for m in _PLACEHOLDER_MARKERS)


def secrets_dhan_env_candidates(root: Path | None = None) -> list[Path]:
    """Ordered candidate paths under secrets_root for Dhan env files."""
    from core.batman_mode import secrets_dhan_env_path, secrets_root

    sr = secrets_root(root)
    return [
        sr / "config" / "dhan.env",
        secrets_dhan_env_path(root),  # <secrets_root>/config/.env
    ]


def resolve_dhan_env_path(root: Path | None = None) -> Path | None:
    """Return the first existing Dhan env file under secrets_root, else None."""
    for path in secrets_dhan_env_candidates(root):
        if path.is_file():
            return path
    return None


def load_dhan_env_values(root: Path | None = None) -> dict[str, str]:
    """Read Dhan-related keys from secrets files (no process env merge)."""
    out: dict[str, str] = {}
    for path in secrets_dhan_env_candidates(root):
        if not path.is_file():
            continue
        raw = dotenv_values(path)
        for k, v in raw.items():
            if not k or v is None:
                continue
            key = str(k).strip()
            if key not in DHAN_ENV_KEYS and not key.startswith("DHAN_"):
                continue
            val = str(v).strip()
            if not val or is_placeholder(val):
                continue
            # first file wins per key; later files only fill gaps
            if key not in out:
                out[key] = val
    return out


def apply_dhan_secrets_env(
    root: Path | None = None, *, override: bool = False
) -> Path | None:
    """Load Dhan secrets into ``os.environ``. Returns path of primary file loaded.

    Only non-placeholder Dhan keys are applied (safe if example templates sit on disk).
    """
    loaded_from = resolve_dhan_env_path(root)
    vals = load_dhan_env_values(root)
    for k, v in vals.items():
        if override or not (os.environ.get(k) or "").strip():
            os.environ[k] = v
    return loaded_from


def dhan_secrets_status(root: Path | None = None) -> dict[str, object]:
    """Non-secret status dict for smoke/docs (never includes PIN/TOTP/JWT values)."""
    path = resolve_dhan_env_path(root)
    vals = load_dhan_env_values(root)
    present = sorted(vals.keys())
    return {
        "secrets_file": str(path) if path else None,
        "candidates": [str(p) for p in secrets_dhan_env_candidates(root)],
        "keys_present": present,
        "has_client_code": bool(
            vals.get("DHAN_CLIENT_CODE") or vals.get("DHAN_CLIENT_ID") or vals.get("FTLTP_CLIENT_ID")
        ),
        "has_pin": bool(vals.get("DHAN_PIN") or vals.get("FTLTP_PIN")),
        "has_totp_secret": bool(vals.get("DHAN_TOTP_SECRET") or vals.get("FTLTP_TOTP_SECRET")),
        "has_access_token": bool(vals.get("DHAN_ACCESS_TOKEN")),
        "pin_totp_ready": bool(
            (vals.get("DHAN_PIN") or vals.get("FTLTP_PIN"))
            and (vals.get("DHAN_TOTP_SECRET") or vals.get("FTLTP_TOTP_SECRET"))
            and (
                vals.get("DHAN_CLIENT_CODE")
                or vals.get("DHAN_CLIENT_ID")
                or vals.get("FTLTP_CLIENT_ID")
            )
        ),
    }
