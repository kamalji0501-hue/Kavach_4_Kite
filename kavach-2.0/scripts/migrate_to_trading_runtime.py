#!/usr/bin/env python3
"""
One-time migration: copy in-repo logs/data/secrets into Trading_Runtime.

Run with bots STOPPED:
  .venv/bin/python scripts/migrate_to_trading_runtime.py --dry-run
  .venv/bin/python scripts/migrate_to_trading_runtime.py

Does NOT delete in-repo copies (rollback-safe).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TR_DEFAULT = Path("/home/kamalji0501e/Batman Algo Files/Trading_Runtime")


def _copy_tree(src: Path, dst: Path, *, dry_run: bool) -> int:
    """Copy files from src into dst (merge). Returns file count."""
    if not src.exists():
        print(f"  skip missing: {src}")
        return 0
    count = 0
    if src.is_file():
        if dry_run:
            print(f"  would copy file: {src} -> {dst}")
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  copied file: {src} -> {dst}")
        return 1
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        target = dst / rel
        if dry_run:
            print(f"  would copy: {rel}")
            count += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(item, target)
            count += 1
        else:
            # Prefer newer or overwrite if sizes differ
            if item.stat().st_mtime >= target.stat().st_mtime:
                shutil.copy2(item, target)
                count += 1
    print(f"  tree {src.name}: {count} file(s) -> {dst}")
    return count


def _copy_secret_file(src: Path, dst: Path, *, dry_run: bool) -> bool:
    if not src.is_file():
        return False
    if dry_run:
        print(f"  would copy secret: {src} -> {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  copied secret: {src} -> {dst}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate runtime into Trading_Runtime")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--trading-runtime",
        type=Path,
        default=TR_DEFAULT,
        help="Trading_Runtime root (default: Batman Algo Files/Trading_Runtime)",
    )
    args = parser.parse_args()

    from core.batman_mode import (
        data_reports_base,
        ensure_runtime_layout,
        logs_base,
        secrets_root,
        workspace_root,
    )

    ws = workspace_root()
    tr = args.trading_runtime.resolve()
    logs_dst = logs_base(ws)
    data_dst = data_reports_base(ws)
    cred_dst = secrets_root(ws)

    print(f"workspace: {ws}")
    print(f"Trading_Runtime: {tr}")
    print(f"logs_dst: {logs_dst}")
    print(f"data_dst: {data_dst}")
    print(f"cred_dst: {cred_dst}")
    if args.dry_run:
        print("DRY RUN — no writes")

    if not args.dry_run:
        ensure_runtime_layout(ws)
        for name in (
            "Logs",
            "Data",
            "Credentials",
            "Temp",
            "Cache",
            "Backups",
            "Health",
            "Exports",
            "Screenshots",
            "Database",
            "User",
            "Config",
        ):
            (tr / name).mkdir(parents=True, exist_ok=True)

    # 1) logs + data from in-repo runtime dirs
    print("\n=== logs_runtime -> Logs ===")
    _copy_tree(ws / "logs_runtime", logs_dst, dry_run=args.dry_run)
    print("\n=== data_runtime -> Data ===")
    _copy_tree(ws / "data_runtime", data_dst, dry_run=args.dry_run)

    # kavach-2.0 may have small local copies
    k2 = ws / "kavach-2.0"
    if (k2 / "logs_runtime").exists():
        print("\n=== kavach-2.0/logs_runtime (merge) ===")
        _copy_tree(k2 / "logs_runtime", logs_dst, dry_run=args.dry_run)
    if (k2 / "data_runtime").exists():
        print("\n=== kavach-2.0/data_runtime (merge) ===")
        _copy_tree(k2 / "data_runtime", data_dst, dry_run=args.dry_run)

    # 2) secrets
    print("\n=== credentials ===")
    _copy_secret_file(
        ws / "config" / ".env",
        cred_dst / "config" / ".env",
        dry_run=args.dry_run,
    )
    if (k2 / "config" / ".env").is_file():
        # Prefer root .env; only copy k2 if dest missing
        dest = cred_dst / "config" / ".env"
        if args.dry_run or not dest.exists():
            _copy_secret_file(k2 / "config" / ".env", dest, dry_run=args.dry_run)

    bot_dirs = [
        ws / "telegram" / "bots",
        k2 / "telegram" / "bots",
    ]
    for bots_root in bot_dirs:
        if not bots_root.is_dir():
            continue
        for bot_dir in sorted(bots_root.iterdir()):
            if not bot_dir.is_dir():
                continue
            token = bot_dir / "token.env"
            if token.is_file():
                _copy_secret_file(
                    token,
                    cred_dst / "telegram" / "bots" / bot_dir.name / "token.env",
                    dry_run=args.dry_run,
                )

    # legacy secrets_runtime if any content
    for sr in (ws / "secrets_runtime", k2 / "secrets_runtime"):
        if sr.exists() and any(sr.rglob("*")):
            print(f"\n=== merge {sr} ===")
            _copy_tree(sr, cred_dst, dry_run=args.dry_run)

    # legacy in-repo data/access_token.json -> shared
    legacy_token = ws / "data" / "access_token.json"
    shared_token = data_dst / "data" / "shared" / "access_token.json"
    if legacy_token.is_file() and (args.dry_run or not shared_token.exists()):
        print("\n=== legacy access_token.json ===")
        _copy_secret_file(legacy_token, shared_token, dry_run=args.dry_run)

    print("\nDONE" + (" (dry-run)" if args.dry_run else ""))
    print("In-repo logs_runtime/data_runtime were NOT deleted (rollback-safe).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
