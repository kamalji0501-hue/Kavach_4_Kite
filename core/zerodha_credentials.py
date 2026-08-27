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


def load_zerodha_order_creds(root: Path | None = None) -> ZerodhaOrderCreds:
    for env_path in candidate_env_paths():
        if env_path.is_file():
            load_dotenv(env_path, override=False)

    api_key = os.environ.get("ZERODHA_API_KEY", "").strip()
    access = os.environ.get("ZERODHA_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("ZERODHA_USER_ID", "").strip()
    source = "env" if api_key and access else ""

    for path in candidate_session_paths(root):
        if not path.is_file():
            continue
        data = _read_json(path)
        api_key = api_key or str(data.get("api_key") or "").strip()
        tok = str(data.get("access_token") or data.get("token") or "").strip()
        if tok:
            access = tok
            source = str(path)
        user_id = user_id or str(data.get("user_id") or "").strip()
        if api_key and access:
            break

    creds = ZerodhaOrderCreds(
        api_key=api_key, access_token=access, user_id=user_id, source=source
    )
    if creds.ok:
        logger.info(
            "Zerodha order creds ready last4=%s source=%s",
            creds.access_token[-4:],
            Path(str(creds.source)).name if creds.source else "env",
        )
    else:
        logger.warning("Zerodha order creds missing api_key or access_token")
    return creds


def watch_path(root: Path | None = None) -> Path:
    """Primary file Kavach watches for a refreshed feeder token."""
    for path in candidate_session_paths(root):
        if path.is_file():
            return path
    from core.token_fanout import feeder_zerodha_json_path

    return feeder_zerodha_json_path()


def start_zerodha_token_watch(
    broker,
    *,
    root: Path | None = None,
    poll_seconds: float = 30.0,
    on_token_ready: Callable[[str], None] | None = None,
) -> threading.Event:
    """Reload Kavach Kite REST when Datafeedbot / TOKEN saves a new access_token."""
    stop = threading.Event()
    paths = [p for p in candidate_session_paths(root)]

    def _newest() -> tuple[float, Path | None]:
        best = 0.0
        hit: Path | None = None
        for path in paths:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > best:
                best = mtime
                hit = path
        return best, hit

    def _loop() -> None:
        last, _ = _newest()
        while not stop.wait(timeout=poll_seconds):
            mtime, hit = _newest()
            if mtime <= last or hit is None:
                continue
            last = mtime
            creds = load_zerodha_order_creds(root)
            if not creds.ok:
                continue
            if broker is None and on_token_ready is not None:
                try:
                    on_token_ready(creds.access_token)
                except Exception as exc:
                    logger.error("Zerodha token bootstrap failed: %s", exc)
                continue
            reload_fn = getattr(broker, "hot_reload_token", None)
            if callable(reload_fn):
                try:
                    reload_fn(creds.api_key, creds.access_token)
                    logger.info("Kavach Zerodha REST hot-reloaded last4=%s", creds.access_token[-4:])
                except Exception as exc:
                    logger.error("Zerodha hot-reload failed: %s", exc)

    threading.Thread(target=_loop, daemon=True, name="zerodha-token-watch").start()
    return stop
