"""KAVACH ↔ SARANSH session boundaries (manifest, feed wipe, auto-restart)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from core import utils
from core.batman_mode import get_mode, workspace_root
from core.optional_bot_startup import optional_bot_enabled
from core.saransh_paths import (
    ato_cycle_feed_path,
    ato_cycle_state_path,
    saransh_analytics_dir,
    session_manifest_path,
)

logger = logging.getLogger(__name__)


def _root(root: Path | None) -> Path:
    return root or workspace_root()


def phase1_saransh_root(root: Path | None = None) -> Path:
    """Phase 1 tree that owns the live SARANSH process (parent of kavach-2.0).

    ``kavach-2.0/`` also has ``run_saransh.py``, but Phase 1 runs SARANSH from the
    parent workspace (shared ``.venv`` + ``telegram/bots/saransh/token.env``).
    """
    base = _root(root).resolve()
    if base.name == "kavach-2.0":
        parent = base.parent
        parent_token = parent / "telegram" / "bots" / "saransh" / "token.env"
        if (parent / "run_saransh.py").is_file() and (
            parent_token.is_file() or (parent / ".venv").exists()
        ):
            return parent
    if (base / "run_saransh.py").is_file():
        return base
    parent = base.parent
    if (parent / "run_saransh.py").is_file():
        return parent
    return base


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _delete_feed_files(root: Path) -> None:
    for path in (ato_cycle_feed_path(root), ato_cycle_state_path(root)):
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            logger.warning("SARANSH feed delete failed %s: %s", path, exc)


def _archive_saransh_xlsx(root: Path) -> list[str]:
    """Move today's session XLSX into archive/ (best effort)."""
    src_dir = saransh_analytics_dir(root)
    archive = src_dir / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    if not src_dir.is_dir():
        return moved
    for path in sorted(src_dir.glob("summary_*.xlsx")):
        try:
            dest = archive / path.name
            if dest.exists():
                dest.unlink()
            path.replace(dest)
            moved.append(path.name)
        except OSError as exc:
            logger.warning("SARANSH XLSX archive failed %s: %s", path, exc)
    return moved


def read_session_manifest(*, root: Path | None = None) -> dict[str, Any] | None:
    path = session_manifest_path(_root(root))
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def saransh_session_reset_feeds_only(*, root: Path | None = None) -> None:
    """Register wizard start — wipe feeds only; no SARANSH restart."""
    base = _root(root)
    _delete_feed_files(base)
    manifest = read_session_manifest(root=base)
    if manifest and manifest.get("status") == "completed":
        manifest["status"] = "idle"
        manifest["restart_reason"] = None
        _atomic_write_json(session_manifest_path(base), manifest)


def saransh_session_arm(
    *,
    root: Path | None = None,
    deployment_file: str,
    restart_reason: str = "register_confirm",
) -> dict[str, Any]:
    """Register confirm — fresh manifest + feed wipe + auto restart."""
    base = _root(root)
    now = utils.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    session_id = utils.now_ist().strftime("%Y%m%d_%H%M%S")
    _delete_feed_files(base)
    manifest = {
        "session_id": session_id,
        "status": "armed",
        "deployed_at_ist": now,
        "completed_at_ist": None,
        "deployment_file": deployment_file,
        "mode": get_mode(base),
        "restart_reason": restart_reason,
    }
    _atomic_write_json(session_manifest_path(base), manifest)
    restart = restart_saransh(root=base, reason=restart_reason)
    return {"manifest": manifest, "restart": restart}


def saransh_session_complete(*, root: Path | None = None) -> dict[str, Any]:
    """Batman Complete — archive XLSX, wipe feeds, manifest completed, auto restart."""
    base = _root(root)
    archived = _archive_saransh_xlsx(base)
    _delete_feed_files(base)
    now = utils.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    prior = read_session_manifest(root=base) or {}
    manifest = {
        "session_id": prior.get("session_id") or utils.now_ist().strftime("%Y%m%d_%H%M%S"),
        "status": "completed",
        "deployed_at_ist": prior.get("deployed_at_ist"),
        "completed_at_ist": now,
        "deployment_file": prior.get("deployment_file"),
        "mode": get_mode(base),
        "restart_reason": "batman_complete",
    }
    _atomic_write_json(session_manifest_path(base), manifest)
    restart = restart_saransh(root=base, reason="batman_complete")
    return {"archived_xlsx": archived, "manifest": manifest, "restart": restart}


def restart_saransh(*, root: Path | None = None, reason: str = "manual") -> dict[str, Any]:
    """
    Stop then start SARANSH when token + enabled (OQ-P1-21 A).

    Always runs stop first — even if operator manually stopped SARANSH —
    then launches start Saransh (.sh on Linux, .bat on Windows).
    """
    import sys

    from core.utils import get_venv_python

    base = phase1_saransh_root(root)
    eligible, detail = optional_bot_enabled("saransh", root=base)
    if not eligible:
        logger.info("SARANSH restart skipped: %s", detail)
        return {"skipped": True, "reason": detail}

    python = get_venv_python(base)
    stop_script = base / "scripts" / "stop_saransh.py"
    start_sh = base / "Execution" / "Start Bots" / "start Saransh.sh"
    start_bat = base / "Execution" / "Start Bots" / "start Saransh.bat"
    launcher = start_sh if start_sh.is_file() else start_bat

    if python.is_file() and stop_script.is_file():
        subprocess.run(
            [str(python), str(stop_script), "--silent"],
            cwd=base,
            check=False,
        )
    else:
        logger.warning("SARANSH stop script missing — continuing to start")

    if not launcher.is_file():
        return {"skipped": True, "reason": "start Saransh launcher missing"}

    if sys.platform == "win32":
        cmd = f'start "SARANSH Bot - Running" cmd /k call "{launcher}"'
        subprocess.run(cmd, cwd=base, shell=True, check=False)
    else:
        subprocess.Popen(
            ["bash", str(launcher)],
            cwd=base,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    logger.info("SARANSH restart launched (reason=%s) root=%s", reason, base)
    return {"ok": True, "reason": reason, "root": str(base)}


def clear_restart_reason(*, root: Path | None = None) -> None:
    """After SARANSH Telegram ack — avoid duplicate messages on poll restart."""
    base = _root(root)
    manifest = read_session_manifest(root=base)
    if not manifest or not manifest.get("restart_reason"):
        return
    manifest["restart_reason"] = None
    _atomic_write_json(session_manifest_path(base), manifest)
