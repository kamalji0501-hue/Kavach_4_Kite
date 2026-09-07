"""Fan-out Dhan JWT + Zerodha token to Kavach and Datafeedbot runtimes."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from core.batman_mode import access_token_path, shared_data_dir
from core.token_store import TokenStore

logger = logging.getLogger("batman.token_fanout")


def feeder_runtime() -> Path:
    env = os.environ.get("DATAFEEDBOT_RUNTIME", "").strip()
    if env:
        return Path(env)
    return Path("/home/ubuntu/Datafeedbot_Runtime")


def feeder_dhan_jwt_path() -> Path:
    return feeder_runtime() / "Data" / "shared" / "access_token.json"


def feeder_zerodha_json_path() -> Path:
    return feeder_runtime() / "Data" / "shared" / "zerodha_access_token.json"


def feeder_zerodha_env_path() -> Path:
    return feeder_runtime() / "Credentials" / "zerodha" / "zerodha.env"


def kavach_zerodha_json_path(root: Path | None = None) -> Path:
    return shared_data_dir(root) / "zerodha_access_token.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def persist_dhan_jwt(token: str, *, root: Path | None = None, source: str = "kavach2") -> None:
    """Save Dhan JWT to Kavach TokenStore and Datafeedbot runtime."""
    tok = (token or "").strip()
    if not tok:
        raise ValueError("empty Dhan JWT")
    TokenStore(path=access_token_path(root)).save(tok)
    payload = {
        "access_token": tok,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
    }
    dest = feeder_dhan_jwt_path()
    try:
        _atomic_write_json(dest, payload)
        logger.info("Dhan JWT also saved for Feeder → %s", dest)
    except Exception as exc:
        logger.error("Feeder Dhan JWT fan-out failed (%s): %s", dest, exc)
        raise


def _kavach_zerodha_env_path() -> Path:
    return Path("/home/ubuntu/Trading_Runtime_Rahul/Credentials/zerodha/zerodha.env")


def persist_zerodha_token(
    access_token: str,
    *,
    root: Path | None = None,
    source: str = "kavach2",
    user_id: str = "",
) -> datetime:
    token = (access_token or "").strip()
    if not token:
        raise ValueError("empty Zerodha access_token")
    saved_at = datetime.now()
    payload = {
        "access_token": token,
        "saved_at": saved_at.isoformat(timespec="seconds"),
        "source": source,
    }
    _atomic_write_json(kavach_zerodha_json_path(root), payload)
    _atomic_write_json(feeder_zerodha_json_path(), payload)
    env_targets = [feeder_zerodha_env_path(), _kavach_zerodha_env_path()]
    for env_path in env_targets:
        try:
            from datafeedbot.auth.zerodha_token import _upsert_env_token

            _upsert_env_token(env_path, token, user_id=user_id)
        except Exception as exc:
            logger.warning("zerodha.env upsert failed (%s): %s", env_path, exc)
            _upsert_zerodha_env_local(env_path, token)
    logger.info(
        "Zerodha token saved last4=%s feeder=%s kavach=%s",
        token[-4:],
        feeder_zerodha_json_path(),
        kavach_zerodha_json_path(root),
    )
    return saved_at


def _upsert_zerodha_env_local(env_path: Path, access_token: str) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    kv: dict[str, str] = {}
    order: list[str] = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k not in kv:
            order.append(k)
        kv[k] = v.strip()
    if "ZERODHA_ACCESS_TOKEN" not in order:
        order.append("ZERODHA_ACCESS_TOKEN")
    kv["ZERODHA_ACCESS_TOKEN"] = access_token
    env_path.write_text(
        "\n".join(f"{k}={kv.get(k, '')}" for k in order) + "\n", encoding="utf-8"
    )


def clear_dhan_jwt(*, root: Path | None = None) -> None:
    TokenStore(path=access_token_path(root)).clear()
    dest = feeder_dhan_jwt_path()
    try:
        if dest.is_file():
            dest.unlink()
            logger.info("Feeder Dhan JWT cleared → %s", dest)
    except Exception as exc:
        logger.warning("Feeder Dhan JWT clear failed: %s", exc)


def _clear_zerodha_env(env_path: Path) -> None:
    if not env_path.is_file():
        return
    _upsert_zerodha_env_local(env_path, "")


def _clear_kite_session(path: Path) -> None:
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    if "access_token" in data:
        data["access_token"] = ""
    if "token" in data:
        data["token"] = ""
    _atomic_write_json(path, data)


def clear_zerodha_token(*, root: Path | None = None) -> None:
    """Remove Zerodha token from Kavach + Feeder files (same set persist writes)."""
    for path in (kavach_zerodha_json_path(root), feeder_zerodha_json_path()):
        try:
            if path.is_file():
                path.unlink()
                logger.info("Zerodha JSON cleared → %s", path)
        except Exception as exc:
            logger.warning("Zerodha JSON clear failed (%s): %s", path, exc)
    for env_path in (feeder_zerodha_env_path(), _kavach_zerodha_env_path()):
        try:
            _clear_zerodha_env(env_path)
        except Exception as exc:
            logger.warning("zerodha.env clear failed (%s): %s", env_path, exc)
    for sess in (
        feeder_runtime() / "Credentials" / "zerodha" / "kite_session.json",
        Path("/home/ubuntu/Trading_Runtime_Rahul/Credentials/zerodha/kite_session.json"),
    ):
        try:
            _clear_kite_session(sess)
        except Exception as exc:
            logger.warning("kite_session clear failed (%s): %s", sess, exc)
