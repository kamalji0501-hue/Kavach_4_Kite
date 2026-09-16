"""Load Zerodha api_key + access_token for Kavach order REST.

Reuses the Datafeedbot session. Does not start KiteTicker. Never logs secrets.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

logger = logging.getLogger("batman.zerodha.creds")

_LIVE_ORDER_BROKER = None


@dataclass
class ZerodhaOrderCreds:
    api_key: str = ""
    access_token: str = ""
    user_id: str = ""
    source: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.api_key and self.access_token)


def _feeder_runtime() -> Path:
    env = os.environ.get("DATAFEEDBOT_RUNTIME", "").strip()
    if env:
        return Path(env)
    return Path("/home/ubuntu/Datafeedbot_Runtime")


def candidate_session_paths(root: Path | None = None) -> list[Path]:
    from core.batman_mode import shared_data_dir, workspace_root
    from core.token_fanout import feeder_zerodha_json_path, kavach_zerodha_json_path

    root = root or workspace_root()
    feeder = _feeder_runtime()
    return [
        feeder / "Credentials" / "zerodha" / "kite_session.json",
        feeder_zerodha_json_path(),
        kavach_zerodha_json_path(root),
        shared_data_dir(root) / "zerodha_access_token.json",
        Path("/home/ubuntu/Trading_Runtime_Rahul/Credentials/zerodha/kite_session.json"),
    ]


def candidate_env_paths() -> list[Path]:
    feeder = _feeder_runtime()
    return [
        feeder / "Credentials" / "zerodha" / "zerodha.env",
        Path("/home/ubuntu/Trading_Runtime_Rahul/Credentials/zerodha/zerodha.env"),
        Path("/home/ubuntu/rahul_Changes/kavach-2.0/config/zerodha.env"),
    ]


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_zerodha_order_creds(
    root: Path | None = None, *, log: bool = True
) -> ZerodhaOrderCreds:
    for env_path in candidate_env_paths():
        if env_path.is_file():
            load_dotenv(env_path, override=False)

    api_key = os.environ.get("ZERODHA_API_KEY", "").strip()
    user_id = os.environ.get("ZERODHA_USER_ID", "").strip()
    access = ""
    source = ""

    # Access token only from Kavach/Feeder JSON that persist/clear write.
    # Never use process env leftover after DEACTIVATE.
    from core.token_fanout import feeder_zerodha_json_path, kavach_zerodha_json_path

    for path in (kavach_zerodha_json_path(root), feeder_zerodha_json_path()):
        if not path.is_file():
            continue
        data = _read_json(path)
        tok = str(data.get("access_token") or data.get("token") or "").strip()
        if tok:
            access = tok
            source = str(path)
            user_id = user_id or str(data.get("user_id") or "").strip()
            break

    for path in candidate_session_paths(root):
        if not path.is_file():
            continue
        data = _read_json(path)
        api_key = api_key or str(data.get("api_key") or "").strip()

    creds = ZerodhaOrderCreds(
        api_key=api_key, access_token=access, user_id=user_id, source=source
    )
    if creds.ok:
        if log:
            logger.info(
                "Zerodha order creds ready last4=%s source=%s",
                creds.access_token[-4:],
                Path(str(creds.source)).name if creds.source else "env",
            )
    elif log:
        logger.warning("Zerodha order creds missing api_key or access_token")
    return creds


def sync_live_zerodha_token(
    broker=None,
    *,
    root: Path | None = None,
    on_token_ready: Callable[[str], None] | None = None,
    force: bool = False,
) -> bool:
    """Push the disk Kite token into the live REST client used by Register/orders."""
    global _LIVE_ORDER_BROKER
    creds = load_zerodha_order_creds(root, log=False)
    live = broker if broker is not None else _LIVE_ORDER_BROKER
    if live is not None:
        register_live_order_broker(live)
        live = _LIVE_ORDER_BROKER
    if not creds.ok:
        clearer = getattr(live, "clear_access_token", None) if live is not None else None
        if callable(clearer):
            try:
                clearer()
            except Exception as exc:
                logger.warning("Zerodha order token clear failed: %s", exc)
        return False
    if live is None:
        if on_token_ready is not None:
            on_token_ready(creds.access_token)
            return True
        return False
    current = str(getattr(live, "_access_token", "") or "").strip()
    if not force and current == creds.access_token:
        return False
    reload_fn = getattr(live, "hot_reload_token", None)
    if not callable(reload_fn):
        return False
    reload_fn(creds.api_key, creds.access_token)
    logger.info("Kavach Zerodha REST synced last4=%s", creds.access_token[-4:])
    return True


def watch_path(root: Path | None = None) -> Path:
    """Primary file Kavach watches for a refreshed feeder token."""
    for path in candidate_session_paths(root):
        if path.is_file():
            return path
    from core.token_fanout import feeder_zerodha_json_path

    return feeder_zerodha_json_path()


def register_live_order_broker(broker) -> None:
    global _LIVE_ORDER_BROKER
    _LIVE_ORDER_BROKER = broker


def clear_live_order_broker() -> None:
    """TOKEN Kite deactivate — drop in-memory order token now."""
    broker = _LIVE_ORDER_BROKER
    clearer = getattr(broker, "clear_access_token", None) if broker is not None else None
    if callable(clearer):
        clearer()


def start_zerodha_token_watch(
    broker,
    *,
    root: Path | None = None,
    poll_seconds: float = 5.0,
    on_token_ready: Callable[[str], None] | None = None,
) -> threading.Event:
    """Reload Kavach Kite REST when TOKEN / feeder writes a new access_token.

    Watch the token string (not file mtime). mtime-only missed Kavach Register
    after a TOKEN paste because the live REST client kept the old token.
    """
    stop = threading.Event()
    register_live_order_broker(broker)

    def _fp() -> str:
        creds = load_zerodha_order_creds(root, log=False)
        return creds.access_token if creds.ok else ""

    def _loop() -> None:
        last = _fp()
        while not stop.wait(timeout=poll_seconds):
            fp = _fp()
            live = _LIVE_ORDER_BROKER if _LIVE_ORDER_BROKER is not None else broker
            mem = str(getattr(live, "_access_token", "") or "").strip() if live is not None else ""
            if fp == last and (not fp or mem == fp):
                continue
            last = fp
            try:
                sync_live_zerodha_token(
                    live if live is not None else broker,
                    root=root,
                    on_token_ready=on_token_ready,
                    force=True,
                )
            except Exception as exc:
                logger.error("Zerodha live token sync failed: %s", exc)

    threading.Thread(target=_loop, daemon=True, name="zerodha-token-watch").start()
    return stop
