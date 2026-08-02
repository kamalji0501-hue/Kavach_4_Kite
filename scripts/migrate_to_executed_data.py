#!/usr/bin/env python3
"""
Move runtime from Desktop/Batman-Runtime to Desktop/Batman Executed Data.

  Logs            -> Batman Executed Data/Logs
  data + reports  -> Batman Executed Data/Data and Reports

Run with bots STOPPED:
  .venv\\Scripts\\python.exe scripts\\migrate_to_executed_data.py
  .venv\\Scripts\\python.exe scripts\\migrate_to_executed_data.py --dry-run
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
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or item.stat().st_mtime > target.stat().st_mtime:
                    shutil.copy2(item, target)
    else:
        if not dst.exists():
            shutil.copy2(src, dst)
    print(f"  copied: {src} -> {dst}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate Batman-Runtime -> Batman Executed Data folders"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--source",
        default="",
        help="Legacy runtime root (default: %%USERPROFILE%%/Desktop/Batman-Runtime)",
    )
    args = parser.parse_args()

    from core.batman_mode import (
        data_reports_base,
        ensure_runtime_layout,
        logs_base,
        workspace_root,
    )

    ws = workspace_root()
    legacy = (
        Path(args.source).expanduser().resolve()
        if args.source.strip()
        else (Path.home() / "Desktop" / "Batman-Runtime").resolve()
    )
    logs_dst = logs_base(ws)
    data_dst = data_reports_base(ws)
    ensure_runtime_layout(ws)

    print(f"Workspace:     {ws}")
    print(f"Legacy source: {legacy}")
    print(f"Logs dest:     {logs_dst}")
    print(f"Data dest:     {data_dst}")
    print()

    if not legacy.is_dir():
        print(f"No legacy folder at {legacy} — nothing to migrate.")
        return 0

    print("Logs:")
    _copy_tree(legacy / "logs", logs_dst, dry_run=args.dry_run)

    print("\nData:")
    _copy_tree(legacy / "data", data_dst / "data", dry_run=args.dry_run)

    print("\nReports:")
    _copy_tree(legacy / "reports", data_dst / "reports", dry_run=args.dry_run)

    print("\nDone. Restart bots via Execution\\Start Bots\\.")
    print(f"Logs:    {logs_dst}")
    print(f"Data:    {data_dst / 'data'}")
    print(f"Reports: {data_dst / 'reports'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
