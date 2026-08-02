#!/usr/bin/env python3
"""Migrate legacy logs into single-root layout: logs/runtime/ only."""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
_IST = ZoneInfo("Asia/Kolkata")

_ROBOT_PREFIXES: dict[str, tuple[str, ...]] = {
    "drishti": ("drishti_", "nifty_ltp_feed_", "nifty_ltp_"),
    "kavach": ("kavach_", "ato_protection_"),
    "jagran": ("jagran_", "incidents_"),
}


def _day_dir_for_date(d: datetime) -> Path:
    return ROOT / "logs" / "runtime" / d.strftime("%Y-%m") / d.strftime("%Y-%m-%d")


def _append_file(src: Path, dest: Path) -> None:
    if not src.exists() or src.stat().st_size == 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    marker = f"\n--- migrated from {src.name} ---\n"
    with open(dest, "a", encoding="utf-8") as out:
        if dest.exists() and dest.stat().st_size > 0:
            out.write(marker)
        out.write(src.read_text(encoding="utf-8", errors="replace"))


def _robot_for_log_name(name: str) -> str | None:
    for robot, prefixes in _ROBOT_PREFIXES.items():
        if any(name.startswith(p) for p in prefixes):
            return robot
    return None


def _move_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return False
    try:
        shutil.move(str(src), str(dst))
    except PermissionError:
        print(f"  skip (locked): {src}")
        return False
    print(f"  moved: {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
    return True


def migrate_bots_folder() -> int:
    moved = 0
    bots_root = ROOT / "logs" / "bots"
    if not bots_root.exists():
        return 0

    today = datetime.now(_IST)
    today_dir = _day_dir_for_date(today)

    for bot in ("drishti", "kavach", "jagran", "main"):
        bot_root = bots_root / bot
        if not bot_root.exists():
            continue
        dest_logs = today_dir / bot / "logs"
        dest_errors = today_dir / bot / "errors"
        dest_logs.mkdir(parents=True, exist_ok=True)
        dest_errors.mkdir(parents=True, exist_ok=True)

        for src in bot_root.rglob("startup.log*"):
            if src.is_file():
                if src.name == "startup.log":
                    _append_file(src, dest_logs / "all.log")
                    try:
                        src.unlink()
                        print(f"  merged: {src.relative_to(ROOT)} -> {dest_logs / 'all.log'}")
                        moved += 1
                    except OSError:
                        print(f"  skip (locked): {src}")
                elif _move_if_exists(src, dest_logs / src.name):
                    moved += 1

        err_src = bot_root / "errors" / "startup_errors.log"
        if err_src.exists():
            _append_file(err_src, dest_errors / "all_errors.log")
            try:
                err_src.unlink()
                moved += 1
            except OSError:
                pass
        for src in (bot_root / "errors").glob("startup_errors.log.*"):
            if _move_if_exists(src, dest_errors / src.name):
                moved += 1

        nifty_src = bot_root / "logs" / "nifty_ltp"
        if bot == "drishti" and nifty_src.is_dir():
            nifty_dst = dest_logs / "nifty_ltp"
            nifty_dst.mkdir(parents=True, exist_ok=True)
            for f in nifty_src.glob("*"):
                if f.is_file() and _move_if_exists(f, nifty_dst / f.name):
                    moved += 1

        for name in ("stdout.log", "stderr.log"):
            src = bot_root / "logs" / name
            if src.exists() and _move_if_exists(src, dest_logs / name):
                moved += 1

    try:
        if bots_root.exists() and not any(bots_root.rglob("*")):
            bots_root.rmdir()
            print("  removed empty logs/bots/")
        elif bots_root.exists():
            legacy = ROOT / "logs" / "archive" / "legacy_bots"
            legacy.mkdir(parents=True, exist_ok=True)
            if not (legacy / "bots").exists():
                shutil.move(str(bots_root), str(legacy / "bots"))
                print(f"  archived remaining logs/bots -> {legacy / 'bots'}")
                moved += 1
    except OSError as exc:
        print(f"  note: could not remove logs/bots: {exc}")

    return moved


def migrate_runtime_day_folders() -> int:
    moved = 0
    runtime_root = ROOT / "logs" / "runtime"
    for day_logs in runtime_root.glob("*/*/logs"):
        day_root = day_logs.parent
        for src in list(day_logs.glob("*.log")):
            if src.name.startswith("runtime_") or src.name == "all.log":
                continue
            robot = _robot_for_log_name(src.name)
            if robot is None:
                continue
            dest_dir = day_root / robot / ("errors" if "_errors" in src.name else "logs")
            if _move_if_exists(src, dest_dir / src.name):
                moved += 1

        flat_errors = day_root / "errors"
        if flat_errors.is_dir():
            for src in list(flat_errors.glob("*")):
                if not src.is_file():
                    continue
                robot = src.name.replace("_errors.log", "")
                if robot in _ROBOT_PREFIXES:
                    dest = day_root / robot / "errors" / "all_errors.log"
                    _append_file(src, dest)
                    try:
                        src.unlink()
                        moved += 1
                    except OSError:
                        pass
            try:
                if flat_errors.exists() and not any(flat_errors.iterdir()):
                    flat_errors.rmdir()
            except OSError:
                pass
    return moved


def main() -> int:
    print("=== Log consolidation (runtime-only) ===\n")
    moved = migrate_bots_folder() + migrate_runtime_day_folders()
    readme = ROOT / "logs" / "README.md"
    readme.write_text(
        "# Logs\n\nSingle root: `logs/runtime/YYYY-MM/YYYY-MM-DD/` — see LOGGING_LAYOUT.md\n",
        encoding="utf-8",
    )
    print(f"\nDone — {moved} item(s) processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
