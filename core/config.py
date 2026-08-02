"""
Batman v3 — Configuration loader.

Loads ``config/settings.json`` and resolves ``${ENV_VAR}`` placeholders
from environment variables (or a ``.env`` file).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .exceptions import ConfigError

_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env(value: Any) -> Any:
    """Recursively replace ``${VAR}`` with ``os.environ[VAR]``."""
    return _resolve_env_impl(value, strict=True)


def _resolve_env_lenient(value: Any) -> Any:
    """Like ``_resolve_env`` but missing vars become empty strings (standalone bots)."""
    return _resolve_env_impl(value, strict=False)


def _resolve_env_impl(value: Any, *, strict: bool) -> Any:
    if isinstance(value, str):

        def _replace(m: re.Match) -> str:
            name = m.group(1)
            env_val = os.environ.get(name, "")
            if not env_val:
                if strict:
                    raise ConfigError(f"Environment variable '{name}' is not set")
                return ""
            return env_val

        return _ENV_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env_impl(v, strict=strict) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_impl(v, strict=strict) for v in value]
    return value


class Config:
    """Immutable (after load) configuration tree.

    Access values with dot-separated keys::

        cfg.get("strategy.lot_size")   # → 75
        cfg.get("modules.ato_protection.enabled")  # → True
    """

    def __init__(self, data: dict[str, Any]):
        self._data = data

    # ── Factory ──────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        settings_path: str | Path = "config/settings.json",
        env_path: str | Path | None = "config/.env",
    ) -> Config:
        """Load config from JSON + .env.

        Args:
            settings_path: Path to ``settings.json``.
            env_path: Path to ``.env`` (optional).

        Returns:
            Populated ``Config`` instance.

        Raises:
            ConfigError: If the file is missing or env vars are unset.
        """
        settings_file = Path(settings_path)
        if not settings_file.exists():
            raise ConfigError(f"Settings file not found: {settings_file}")

        # Load .env first so ${} resolution works
        if env_path:
            env_file = Path(env_path)
            if env_file.exists():
                load_dotenv(env_file)

        with open(settings_file) as fh:
            raw = json.load(fh)

        resolved = _resolve_env(raw)
        cfg = cls(resolved)
        cfg.validate()
        return cfg

    @classmethod
    def load_module_settings(
        cls,
        settings_path: str | Path = "config/settings.json",
        env_path: str | Path | None = "config/.env",
    ) -> Config:
        """Load strategy/ATO settings for standalone bot runners (no orchestrator env).

        Telegram tokens live in ``telegram/bots/<bot>/token.env`` — not here.
        Unset ``${ENV}`` placeholders become empty strings instead of raising.
        Skips ``validate()`` (legacy pin/totp keys not required for Phase 1).
        """
        settings_file = Path(settings_path)
        if not settings_file.exists():
            raise ConfigError(f"Settings file not found: {settings_file}")

        if env_path:
            env_file = Path(env_path)
            if env_file.exists():
                load_dotenv(env_file)

        with open(settings_file, encoding="utf-8") as fh:
            raw = json.load(fh)

        return cls(_resolve_env_lenient(raw))

    # ── Validation ───────────────────────────────────────────

    _REQUIRED_KEYS = [
        "broker.client_code",
        "broker.pin",
        "broker.totp_secret",
        "strategy.index",
        "strategy.lot_size",
        "strategy.entry_day",
        "strategy.expiry_day",
        "strategy.sell_distance",
        "strategy.hedge_gap",
        "strategy.buy_lots",
    ]

    def validate(self) -> None:
        """Check that all required config keys are present and non-empty.

        Raises:
            ConfigError: If any required key is missing or empty.
        """
        missing = []
        for key in self._REQUIRED_KEYS:
            val = self.get(key)
            if val is None or val == "":
                missing.append(key)

        if missing:
            raise ConfigError(f"Missing required config keys: {', '.join(missing)}")

        # Type checks for critical numeric values
        lot_size = self.get("strategy.lot_size")
        if not isinstance(lot_size, (int, float)) or lot_size <= 0:
            raise ConfigError(f"strategy.lot_size must be positive, got: {lot_size}")

        sell_dist = self.get("strategy.sell_distance")
        if not isinstance(sell_dist, (int, float)) or sell_dist <= 0:
            raise ConfigError(f"strategy.sell_distance must be positive, got: {sell_dist}")

        hard_stop = self.get("trailing.hard_stop_loss")
        if hard_stop is not None and hard_stop >= 0:
            raise ConfigError(f"trailing.hard_stop_loss must be negative, got: {hard_stop}")

    # ── Access ───────────────────────────────────────────────

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Get a value using dot-separated path.

        ``cfg.get("strategy.lot_size")`` traverses
        ``data["strategy"]["lot_size"]``.
        """
        keys = dotted_key.split(".")
        node = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def section(self, key: str) -> dict[str, Any]:
        """Return a sub-dict (or empty dict if missing)."""
        val = self.get(key)
        return val if isinstance(val, dict) else {}

    @property
    def raw(self) -> dict[str, Any]:
        """Full config as a dict (read-only intent)."""
        return self._data

    def __repr__(self) -> str:
        modules = self.section("modules")
        enabled = [k for k, v in modules.items() if isinstance(v, dict) and v.get("enabled")]
        return f"<Config modules={enabled}>"
