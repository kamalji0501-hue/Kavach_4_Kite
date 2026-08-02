#!/usr/bin/env python3
"""
One-time migration: move logs, data, reports, and secrets out of the git repo
to Desktop/Batman Executed Data (Logs + Data and Reports) and Batman-Secrets.

Run with bots STOPPED:
  .venv\\Scripts\\python.exe scripts\\migrate_runtime_off_repo.py
  .venv\\Scripts\\python.exe scripts\\migrate_runtime_off_repo.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _copy_tree(src: Path, dst: Path, *, dry_run: bool) -> bool:
    if not src.exists():
        return False
    if dry_run:
        print(f"  would copy: {src} -> {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            for item in src.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(src)
                    target = dst / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copy2(item, target)
        else:
            shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        if not dst.exists():
            shutil.copy2(src, dst)
    print(f"  copied: {src} -> {dst}")
    return True


def _move_file(src: Path, dst: Path, *, dry_run: bool) -> bool:
    if not src.is_file():
        return False
    if dry_run:
        print(f"  would move file: {src} -> {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return False
    shutil.copy2(src, dst)
    print(f"  copied: {src} -> {dst}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate runtime artifacts off repo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from core.batman_mode import (
        daily_test_execution_dir,
        data_reports_base,
        ensure_runtime_layout,
        logs_base,
        reports_root,
        secrets_root,
        shared_data_dir,
        workspace_root,
    )

    ws = workspace_root()
    logs_dst = logs_base(ws)
    data_dst = data_reports_base(ws)
    sr = secrets_root(ws)
    ensure_runtime_layout(ws)

    print(f"Workspace: {ws}")
    print(f"Logs:      {logs_dst}")
    print(f"Data:      {data_dst}")
    print(f"Secrets:   {sr}")
    print()

    # --- logs ---
    print("Logs:")
    for name in ("logs_uat", "logs_dev", "logs_prod", "logs"):
        src = ws / name
        if not src.is_dir():
            continue
        mode = name.replace("logs_", "") if name.startswith("logs_") else "uat"
        if name == "logs":
            dst = logs_dst / "legacy"
        else:
            dst = logs_dst / mode
        _copy_tree(src, dst, dry_run=args.dry_run)

    # --- data modes ---
    print("\nData (per mode):")
    for mode in ("uat", "dev", "prod"):
        src = ws / "data" / mode
        dst = data_dst / "data" / mode
        _copy_tree(src, dst, dry_run=args.dry_run)

    # --- shared data ---
    print("\nData (shared):")
    shared = shared_data_dir(ws)
    shared.mkdir(parents=True, exist_ok=True)
    for name in (
        "access_token.json",
        "nifty_ltp_cache.json",
        "nifty_ltp_feed_config.json",
        "drishti.lock",
        "jagran.lock",
    ):
        _move_file(ws / "data" / name, shared / name, dry_run=args.dry_run)

    # legacy locks at data/*.lock
    for lock in (ws / "data").glob("*.lock"):
        _move_file(lock, shared / lock.name, dry_run=args.dry_run)

    # analytics at data/analytics -> uat analytics if uat mode data missing
    analytics_src = ws / "data" / "analytics"
    if analytics_src.is_dir():
        _copy_tree(analytics_src, data_dst / "data" / "uat" / "analytics", dry_run=args.dry_run)

    # --- UAT positions ---
    print("\nUAT positions:")
    _copy_tree(
        ws / "uat" / "deployed_positions",
        data_dst / "data" / "uat" / "deployed_positions",
        dry_run=args.dry_run,
    )

    # --- daily test / reports ---
    print("\nReports:")
    _copy_tree(ws / "daily_test_execution", daily_test_execution_dir(ws), dry_run=args.dry_run)

    # --- secrets ---
    print("\nSecrets (Telegram + Dhan):")
    sr.mkdir(parents=True, exist_ok=True)
    for bot_dir in (ws / "telegram" / "bots").iterdir() if (ws / "telegram" / "bots").is_dir() else []:
        if not bot_dir.is_dir():
            continue
        token = bot_dir / "token.env"
        if token.is_file():
            dst = sr / "telegram" / "bots" / bot_dir.name / "token.env"
            _move_file(token, dst, dry_run=args.dry_run)
    dhan = ws / "config" / ".env"
    if dhan.is_file():
        _move_file(dhan, sr / "config" / ".env", dry_run=args.dry_run)

    print("\nDone. Restart bots via Execution\\Start Bots\\.")
    print(f"Logs:    {logs_dst}")
    print(f"Data:    {data_dst / 'data'}")
    print(f"Reports: {reports_root(ws)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
