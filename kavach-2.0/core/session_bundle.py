"""Atomic persistence for UAT deployment session artifacts."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from core.batman_mode import session_bundle_dir

logger = logging.getLogger("batman.session_bundle")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def persist_uat_session_bundle(
    *,
    root: Path,
    state_path: Path,
    state_payload: dict[str, Any] | None = None,
    shadow_ledger_path: Path | None = None,
    deployment_path: Path | None = None,
) -> None:
    """Write state JSON atomically; copy shadow ledger + deployment into bundle dir."""
    bundle_dir = session_bundle_dir(root)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    if state_payload is not None:
        _atomic_write_json(state_path, state_payload)
        _atomic_write_json(bundle_dir / "batman_state.snapshot.json", state_payload)

    if shadow_ledger_path and shadow_ledger_path.exists():
        dest = bundle_dir / shadow_ledger_path.name
        shutil.copy2(shadow_ledger_path, dest)

    if deployment_path and deployment_path.exists():
        dest = bundle_dir / deployment_path.name
        shutil.copy2(deployment_path, dest)

    logger.debug("UAT session bundle persisted under %s", bundle_dir)
