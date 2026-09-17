"""Main order-broker selector for Kavach (Zerodha | Dhan).

Feeder LTP sources stay independent. This switch only chooses where
Kavach places / reads live orders and positions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("batman.order_broker")

ALLOWED = ("zerodha", "dhan")
_ENV_KEY = "MAIN_ORDER_BROKER"


def _secrets_config_dir(root: Path | None = None) -> Path:
    from core.batman_mode import secrets_root

    return secrets_root(root) / "config"


def config_path(root: Path | None = None) -> Path:
    return _secrets_config_dir(root) / "order_broker.env"


def normalize_main_broker(name: str | None) -> str:
    raw = str(name or "").strip().lower()
    if raw in {"kite", "zerodha", "z"}:
        return "zerodha"
    if raw in {"dhan", "dhanhq", "tradehull"}:
        return "dhan"
    return ""


def get_main_order_broker(root: Path | None = None) -> str:
    env = normalize_main_broker(os.environ.get(_ENV_KEY, ""))
    if env in ALLOWED:
        return env
    path = config_path(root)
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == _ENV_KEY:
                    got = normalize_main_broker(v)
                    if got in ALLOWED:
                        return got
        except OSError as exc:
            logger.warning("read %s failed: %s", path, exc)
    return "zerodha"


def set_main_order_broker(name: str, root: Path | None = None) -> str:
    got = normalize_main_broker(name)
    if got not in ALLOWED:
        raise ValueError("Main order broker must be zerodha or dhan")
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Kavach main ORDER broker for this instance only.\n"
        f"# Feeder Nifty LTP can still use both Dhan and Zerodha.\n"
        f"{_ENV_KEY}={got}\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)
    os.environ[_ENV_KEY] = got
    logger.info("Main order broker set to %s (%s)", got, path)
    return got


def dhan_client_and_token(root: Path | None = None) -> tuple[str, str]:
    """Return (client_code, jwt) from TokenStore + dhan.env (no secrets logged)."""
    from core.batman_mode import access_token_path
    from core.dhan_credentials import load_dhan_env_values
    from core.token_store import TokenStore

    vals = load_dhan_env_values(root)
    client = (
        vals.get("DHAN_CLIENT_CODE")
        or vals.get("DHAN_CLIENT_ID")
        or os.environ.get("DHAN_CLIENT_CODE", "")
        or os.environ.get("DHAN_CLIENT_ID", "")
    ).strip()
    token = ""
    try:
        tok, _ = TokenStore(path=access_token_path(root)).load()
        token = (tok or "").strip()
    except Exception:
        token = ""
    if not token:
        token = (
            vals.get("DHAN_ACCESS_TOKEN")
            or os.environ.get("DHAN_ACCESS_TOKEN", "")
        ).strip()
    return client, token


def attach_live_broker(broker: Any) -> None:
    """Point web runtime + ATO + in-memory live handle at this broker."""
    try:
        from web.runtime import get_runtime

        rt = get_runtime()
        if rt is not None:
            rt.broker = broker
            ato = getattr(rt, "ato", None)
            if ato is not None and hasattr(ato, "broker"):
                ato.broker = broker
    except Exception as exc:
        logger.warning("attach web runtime broker failed: %s", exc)
    try:
        from core.zerodha_credentials import register_live_order_broker

        register_live_order_broker(broker)
    except Exception:
        pass


def reconnect_main_broker(root: Path | None = None, *, client_code: str = "", access_token: str = "") -> Any:
    from core.batman_mode import workspace_root
    from core.broker_factory import create_broker

    ws = root or workspace_root()
    broker = create_broker(client_code, access_token, ws)
    attach_live_broker(broker)
    return broker
