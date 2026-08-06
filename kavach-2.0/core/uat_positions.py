"""UAT screenshot folder — discover image + positions.json for virtual broker."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from core.batman_mode import is_uat, uat_screenshot_dir, workspace_root

logger = logging.getLogger("batman.uat_positions")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_POSITIONS_FILE = "positions.json"


def find_screenshot_images(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    images = [
        p
        for p in directory.iterdir()
        if p.is_file()
        and p.suffix.lower() in _IMAGE_SUFFIXES
        and not p.name.startswith(".")
        and p.name.lower() != _POSITIONS_FILE
    ]
    images.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return images


def positions_json_path(root: Path | None = None) -> Path:
    return uat_screenshot_dir(root) / _POSITIONS_FILE


def legacy_positions_json_paths(root: Path | None = None) -> list[Path]:
    """Repo-relative books agents/docs still write by habit (not Trading_Runtime)."""
    ws = (root or workspace_root()).resolve()
    paths = [ws / "uat" / "deployed_positions" / _POSITIONS_FILE]
    # Parent monorepo uat/ when workspace is kavach-2.0/
    if ws.name == "kavach-2.0":
        paths.append(ws.parent / "uat" / "deployed_positions" / _POSITIONS_FILE)
    return paths


def _file_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (int(st.st_mtime_ns), int(st.st_size))


def _book_recency(path: Path) -> tuple[str, int]:
    """Prefer Sensibull ``captured_at``; fall back to mtime.

    Mirror syncs bump mtime, so mtime-only ranking can re-promote an old
    repo-local file after we just copied the good book into it.
    """
    captured = ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            captured = str(data.get("captured_at") or "").strip()
    except Exception:
        captured = ""
    mtime = (_file_fingerprint(path) or (0, 0))[0]
    return (captured, mtime)


def sync_positions_mirrors_from_canonical(root: Path | None = None) -> Path:
    """Overwrite repo-local uat/ copies from Trading_Runtime (one-way)."""
    root = root or workspace_root()
    canonical = positions_json_path(root)
    if not canonical.is_file():
        return canonical
    try:
        payload = canonical.read_bytes()
    except OSError:
        return canonical
    for mirror in legacy_positions_json_paths(root):
        try:
            if mirror.resolve() == canonical.resolve():
                continue
        except OSError:
            continue
        try:
            if mirror.is_file() and mirror.read_bytes() == payload:
                continue
        except OSError:
            pass
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_bytes(payload)
        logger.info("UAT positions: synced mirror %s from canonical", mirror)
    return canonical


def reconcile_uat_positions_books(root: Path | None = None) -> Path:
    """Make Trading_Runtime the only live book; absorb newer repo-local writes.

    Agents and FAST_UAT docs often write ``kavach-2.0/uat/deployed_positions/positions.json``
    while ShadowBroker/Register read ``Trading_Runtime/.../positions.json``. When those
    diverge, Register shows the old \"cache\" book after Batman Complete / Register.
    """
    root = root or workspace_root()
    canonical = positions_json_path(root)
    seen: set[Path] = set()
    candidates: list[Path] = []
    for path in [canonical, *legacy_positions_json_paths(root)]:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not path.is_file() or resolved in seen:
            continue
        seen.add(resolved)
        candidates.append(path)

    if not candidates:
        return canonical

    newest = max(candidates, key=_book_recency)
    if newest.resolve() != canonical.resolve():
        try:
            same = canonical.is_file() and newest.read_bytes() == canonical.read_bytes()
        except OSError:
            same = False
        if not same:
            canonical.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(newest, canonical)
            logger.warning(
                "UAT positions: promoted newer book %s → canonical %s "
                "(repo-local write was ahead of Trading_Runtime — this caused stale "
                "Register PE BUY legs)",
                newest,
                canonical,
            )

    return sync_positions_mirrors_from_canonical(root)


def load_positions_fixture(root: Path | None = None) -> dict[str, Any]:
    root = root or workspace_root()
    reconcile_uat_positions_books(root)
    path = positions_json_path(root)
    if not path.is_file():
        raise FileNotFoundError(
            f"UAT positions file missing: {path}\n"
            "Paste Sensibull screenshot in uat/deployed_positions/ and run Mode\\Prepare-UAT.bat"
        )
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "legs" not in data:
        raise ValueError(f"Invalid UAT positions JSON: {path}")
    return data


def uat_register_precheck(root: Path | None = None) -> tuple[bool, str]:
    """Called before KAVACH register in UAT — screenshot or positions required."""
    root = root or workspace_root()
    if not is_uat(root):
        return True, ""

    reconcile_uat_positions_books(root)
    shot_dir = uat_screenshot_dir(root)
    images = find_screenshot_images(shot_dir)
    pos_path = positions_json_path(root)

    if images:
        return True, f"UAT screenshot ready: {images[0].name} (Register will OCR on tap)"

    if pos_path.is_file():
        return True, f"UAT positions ready: {pos_path.name}"

    return (
        False,
        f"UAT: no screenshot in {shot_dir}. "
        "Paste Sensibull screenshot there before /register.",
    )
