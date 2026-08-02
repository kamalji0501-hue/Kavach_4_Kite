"""UAT screenshot folder — discover image + positions.json for virtual broker."""

from __future__ import annotations

import json
import logging
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


def load_positions_fixture(root: Path | None = None) -> dict[str, Any]:
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
