"""
Batman v3 — Telegram Bot Config Loader.

Each bot (DRISHTI, KAVACH, LAKSHMI, SANCHALAK, SARANSH, JAGRAN) has its own fully isolated directory under
telegram/bots/<name>/ containing exactly TWO config files:

    token.env      — SECRETS ONLY  (BOT_TOKEN, CHAT_ID)
                   !! Never committed to git !!
                   Edit this file to update your Telegram API token.

    params.json   — PARAMETERS ONLY  (timings, thresholds, retries, flags)
                   Safe to commit. No secrets ever go here.
                   Edit this file to tune bot behaviour.

Why two files?
  - Token update → touch ONLY token.env → zero risk to parameters.
  - Parameter tweak → touch ONLY params.json → zero risk to token.
  - Each bot is independently managed — changing KAVACH never affects DRISHTI.

File layout per bot:
    telegram/bots/<name>/
        token.env          ← secrets  (gitignored)
        token.env.example  ← safe template  (committed)
        params.json        ← all tunable parameters  (committed)

Secrets resolution order (first usable match wins):
  1. Desktop ``<secrets_root>/telegram/bots.env`` (consolidated — preferred)
  2. Per-bot ``<secrets_root>/telegram/bots/<name>/token.env``
  3. Repo ``telegram/bots/<name>/token.env`` (legacy)
  4. Process environment variables

Usage::

    from bat_telegram.loader import load_bot_config

    cfg = load_bot_config("drishti")
    cfg.bot_token            # → resolved Telegram API token string
    cfg.chat_id              # → resolved chat ID string
    cfg.params               # → full dict from params.json

    # Hot-reload token only (after editing token.env):
    cfg = load_bot_config("drishti", reload_token=True)

    # Hot-reload params only (after editing params.json):
    cfg = load_bot_config("drishti", reload_params=True)

    # Hot-reload everything:
    cfg = load_bot_config("drishti", reload_token=True, reload_params=True)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from dotenv import dotenv_values

# ── Constants ─────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
_BOTS_DIR = _ROOT / "telegram" / "bots"
# KAVACH 2.0 lives in the kavach-2.0 sub-project (Phase 1 active robot).
# Classic Kavach package removed — Telegram secrets remain under telegram/bots/kavach.
_KAVACH2_BOTS_DIR = _ROOT / "kavach-2.0" / "telegram" / "bots"
# GO is an independent bot — all files under top-level GO/ (not Phase 1).
_GO_BOTS_DIR = _ROOT / "GO" / "telegram" / "bots"
_KNOWN_BOTS = frozenset(
    {
        "drishti",
        "go",
        "jagran",
        "kavach",
        "kavach2",
        "lakshmi",
        "ratripal",
        "sanchalak",
        "saransh",
    }
)


def _bots_dir_for(name: str) -> Path:
    """Return the telegram/bots directory that owns *name*."""
    if name == "kavach2":
        return _KAVACH2_BOTS_DIR
    if name == "go":
        return _GO_BOTS_DIR
    return _BOTS_DIR

# In-process cache:  bot_name → BotConfig
_CACHE: dict[str, BotConfig] = {}


# ── Data class ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BotConfig:
    """Immutable snapshot of one bot's credentials and parameters.

    Attributes:
        name:       Bot name in lowercase  ("drishti" / "jagran" / "kavach" / "lakshmi" / "sanchalak" / "saransh")
        bot_token:  Telegram API token  (sourced from token.env)
        chat_id:    Telegram chat ID    (sourced from token.env)
        params:     Full parameter dict (sourced from params.json)
    """

    name: str
    bot_token: str
    chat_id: str
    params: dict[str, Any]


# ── Internal helpers ──────────────────────────────────────────────────────────


def _load_token(name: str) -> tuple[str, str]:
    """Read bot_token and chat_id.

    Resolution order (first usable token wins):
      1. Desktop consolidated ``<secrets_root>/telegram/bots.env``
      2. Per-bot ``<secrets_root>/telegram/bots/<name>/token.env``
      3. Repo ``telegram/bots/<name>/token.env`` (legacy)
      4. Process environment variables
    """
    from core.batman_mode import secrets_bot_dir
    from core.telegram_credentials import (
        get_bot_credentials,
        is_placeholder,
        secrets_telegram_bots_env_path,
    )

    prefix = name.upper()
    token_key = f"{prefix}_BOT_TOKEN"
    chat_key = f"{prefix}_CHAT_ID"

    bot_token, chat_id, _source = get_bot_credentials(name)
    if bot_token and not is_placeholder(bot_token):
        if not chat_id or is_placeholder(chat_id):
            chat_id = (chat_id or os.environ.get(chat_key, "") or "").strip()
        if chat_id and not is_placeholder(chat_id):
            return bot_token, chat_id

    bots_dir = _bots_dir_for(name)
    candidates = [
        secrets_telegram_bots_env_path(),
        secrets_bot_dir(name) / "token.env",
        bots_dir / name / "token.env",
        _BOTS_DIR / name / "token.env",
    ]
    for env_file in candidates:
        if not env_file.exists():
            continue
        file_vals = dotenv_values(env_file)
        tok = (
            file_vals.get(token_key)
            or os.environ.get(token_key, "")
            or bot_token
            or ""
        ).strip()
        chat = (
            file_vals.get(chat_key)
            or os.environ.get(chat_key, "")
            or chat_id
            or ""
        ).strip()
        if tok and not is_placeholder(tok) and chat and not is_placeholder(chat):
            return tok, chat

    if bot_token and not is_placeholder(bot_token) and chat_id and not is_placeholder(chat_id):
        return bot_token, chat_id

    cons = secrets_telegram_bots_env_path()
    hint = cons if cons.exists() else (secrets_bot_dir(name) / "token.env")
    if not bot_token or is_placeholder(bot_token):
        raise KeyError(
            f"{token_key} is not set in desktop credentials. "
            f"Add it to {cons} (preferred) or {hint}."
        )
    raise KeyError(
        f"{chat_key} is not set in desktop credentials. "
        f"Add it to {cons} (preferred) or per-bot token.env."
    )



def _load_params(name: str) -> dict[str, Any]:
    """Read and return the params.json dict for *name*."""
    params_file = _bots_dir_for(name) / name / "params.json"
    if not params_file.exists():
        params_file = _BOTS_DIR / name / "params.json"

    if not params_file.exists():
        raise FileNotFoundError(
            f"Missing parameters file: {params_file}\n"
            f"Each bot folder must contain a params.json."
        )

    with open(params_file, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {params_file}, found {type(data).__name__}")
    return cast(dict[str, Any], data)


# ── Public API ────────────────────────────────────────────────────────────────


def load_bot_config(
    bot_name: str,
    reload_token: bool = False,
    reload_params: bool = False,
) -> BotConfig:
    """Load (or return cached) config for a named bot.

    Args:
        bot_name:      One of "drishti", "go", "jagran", "kavach", "kavach2", "lakshmi",
                       "sanchalak", "saransh", "ratripal" (case-insensitive).
        reload_token:  Re-read token.env from disk, keeping params unchanged.
                       Use after editing token.env (token update).
        reload_params: Re-read params.json from disk, keeping token unchanged.
                       Use after editing params.json (parameter tuning).

    Returns:
        Fully resolved ``BotConfig`` instance.

    Raises:
        ValueError:        Unknown bot name.
        FileNotFoundError: token.env or params.json missing.
        KeyError:          Token or chat_id not set.
    """
    name = bot_name.strip().lower()

    if name not in _KNOWN_BOTS:
        raise ValueError(f"Unknown bot: '{bot_name}'.  Valid names: {sorted(_KNOWN_BOTS)}")

    cached: BotConfig | None = _CACHE.get(name)

    # ── Full cold load ────────────────────────────────────────────────────────
    if cached is None:
        bot_token, chat_id = _load_token(name)
        params = _load_params(name)
        cfg = BotConfig(name=name, bot_token=bot_token, chat_id=chat_id, params=params)
        _CACHE[name] = cfg
        return cfg

    # ── Selective hot-reload ──────────────────────────────────────────────────
    # Only re-read the file(s) the caller asked for, leave the rest untouched.
    if reload_token and reload_params:
        bot_token, chat_id = _load_token(name)
        params = _load_params(name)
        cfg = BotConfig(name=name, bot_token=bot_token, chat_id=chat_id, params=params)
    elif reload_token:
        bot_token, chat_id = _load_token(name)
        cfg = replace(cached, bot_token=bot_token, chat_id=chat_id)
    elif reload_params:
        params = _load_params(name)
        cfg = replace(cached, params=params)
    else:
        return cached

    _CACHE[name] = cfg
    return cfg


def reload_all() -> None:
    """Evict all cached bot configs.  Next call to load_bot_config() will
    re-read both token.env and params.json from disk for every bot."""
    _CACHE.clear()


def bot_names() -> list[str]:
    """Return sorted list of all known bot names."""
    return sorted(_KNOWN_BOTS)
