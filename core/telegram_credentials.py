"""Telegram credentials on the user desktop / runtime secrets root.

Preferred single file (multi-VPS / multi-user friendly)::

    <secrets_root>/telegram/bots.env

Example keys::

    DRISHTI_BOT_TOKEN=...
    DRISHTI_CHAT_ID=...
    KAVACH_BOT_TOKEN=...
    KAVACH_CHAT_ID=...

Per-bot ``token.env`` files remain a fallback for older layouts.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import dotenv_values

_PLACEHOLDER_MARKERS = ("YOUR_", "PLACEHOLDER", "CHANGEME", "<ENTER", "PASTE")


def is_placeholder(value: str | None) -> bool:
    if value is None or not str(value).strip():
        return True
    upper = str(value).upper()
    return any(m in upper for m in _PLACEHOLDER_MARKERS)


def secrets_telegram_bots_env_path(root: Path | None = None) -> Path:
    """Canonical consolidated Telegram credentials file on the desktop/runtime."""
    from core.batman_mode import secrets_root

    return secrets_root(root) / "telegram" / "bots.env"


def load_consolidated_telegram_env(root: Path | None = None) -> dict[str, str]:
    path = secrets_telegram_bots_env_path(root)
    if not path.is_file():
        return {}
    raw = dotenv_values(path)
    return {str(k): str(v) for k, v in raw.items() if k and v is not None}


def apply_consolidated_telegram_env(
    root: Path | None = None, *, override: bool = False
) -> Path | None:
    """Load consolidated bots.env into ``os.environ``. Returns path if loaded."""
    path = secrets_telegram_bots_env_path(root)
    if not path.is_file():
        return None
    vals = load_consolidated_telegram_env(root)
    for k, v in vals.items():
        if not v:
            continue
        if override or not os.environ.get(k):
            os.environ[k] = v
    return path


def get_bot_credentials(
    bot_name: str, root: Path | None = None
) -> tuple[str, str, str]:
    """Return (token, chat_id, source_description). Empty strings if missing.

    Kavach 2.0 uses the classic KAVACH Telegram identity (@kavach_batmanbot):
    ``kavach2`` resolves ``KAVACH_BOT_TOKEN`` / ``telegram/bots/kavach`` first,
    then falls back to legacy ``KAVACH2_*`` keys if present.
    """
    from core.batman_mode import secrets_bot_dir, workspace_root

    name = bot_name.strip().lower()
    # kavach2 uses classic KAVACH Telegram identity going forward
    lookup_names = ["kavach", "kavach2"] if name == "kavach2" else [name]

    for lookup in lookup_names:
        prefix = lookup.upper()
        token_key = f"{prefix}_BOT_TOKEN"
        chat_key = f"{prefix}_CHAT_ID"

        # 1) consolidated desktop file
        cons = load_consolidated_telegram_env(root)
        tok = (cons.get(token_key) or "").strip()
        chat = (cons.get(chat_key) or "").strip()
        if tok and not is_placeholder(tok):
            return tok, chat, str(secrets_telegram_bots_env_path(root))

        # 2) per-bot under secrets_root
        per = secrets_bot_dir(lookup, root) / "token.env"
        if per.is_file():
            vals = dotenv_values(per)
            tok = (vals.get(token_key) or vals.get("BOT_TOKEN") or "").strip()
            chat = (vals.get(chat_key) or vals.get("CHAT_ID") or "").strip()
            if tok and not is_placeholder(tok):
                return tok, chat, str(per)

        # 3) repo legacy
        ws = root or workspace_root()
        if lookup == "go":
            repo = ws / "GO" / "telegram" / "bots" / lookup / "token.env"
        elif lookup == "kavach2":
            repo = ws / "kavach-2.0" / "telegram" / "bots" / lookup / "token.env"
        else:
            repo = ws / "telegram" / "bots" / lookup / "token.env"
        if repo.is_file():
            vals = dotenv_values(repo)
            tok = (vals.get(token_key) or vals.get("BOT_TOKEN") or "").strip()
            chat = (vals.get(chat_key) or vals.get("CHAT_ID") or "").strip()
            if tok and not is_placeholder(tok):
                return tok, chat, str(repo)

        # 4) process env
        tok = (os.environ.get(token_key) or "").strip()
        chat = (os.environ.get(chat_key) or "").strip()
        if tok and not is_placeholder(tok):
            return tok, chat, "environ"

    return "", "", "missing"


def upsert_bot_credential_key(
    bot_name: str, key_suffix: str, value: str, root: Path | None = None
) -> Path:
    """Update ``<BOT>_<suffix>`` in consolidated bots.env (create file if needed)."""
    name = bot_name.strip().lower()
    prefix = name.upper()
    key = f"{prefix}_{key_suffix.strip().upper()}"
    path = secrets_telegram_bots_env_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else (
        "# Batman consolidated Telegram credentials\n"
    )
    line = f"{key}={value}"
    if re.search(rf"^{re.escape(key)}=", text, flags=re.MULTILINE):
        text = re.sub(rf"^{re.escape(key)}=.*$", line, text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + f"\n\n# --- {prefix} ---\n{line}\n"
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def list_bots_with_credentials(
    bot_names: list[str], root: Path | None = None
) -> list[dict[str, str]]:
    rows = []
    for name in bot_names:
        tok, chat, src = get_bot_credentials(name, root)
        rows.append(
            {
                "bot": name,
                "has_token": "yes" if tok and not is_placeholder(tok) else "no",
                "has_chat_id": "yes" if chat and not is_placeholder(chat) else "no",
                "source": src,
            }
        )
    return rows
