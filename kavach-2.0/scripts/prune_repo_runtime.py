#!/usr/bin/env python3
"""Remove migrated runtime folders from git repo (after migrate_runtime_off_repo.py)."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Whole trees to delete from repo
REMOVE_DIRS = (
    "logs_uat",
    "logs_dev",
    "logs_prod",
    "logs",
    "data",
)

# Under daily_test_execution: remove generated outputs; keep protocol .md in repo
DAILY_PRUNE_SUBDIRS = ("logs",)
DAILY_PRUNE_FILES = ("test_matrix.xlsx", "LATEST_RUN.md")

# UAT book lives on Desktop — remove copies under repo
UAT_POSITIONS_DIR = ROOT / "uat" / "deployed_positions"

README_UAT_POSITIONS = """# UAT positions (runtime — not in git)

Sensibull screenshot + `positions.json` live on Desktop:

`%USERPROFILE%/Desktop/Batman Executed Data/Data and Reports/data/uat/deployed_positions/`

Agent: write book there (FAST_UAT_PROMPT.md). Do not store runtime files in this repo folder.
"""

README_DATA = """# Runtime data moved off-repo

All mode data (`uat`, `dev`, `prod`, `shared`) is under:

`%USERPROFILE%/Desktop/Batman Executed Data/Data and Reports/data/`

See `docs/MULTI_DEV_SETUP.md`.
"""


def _rm_tree(path: Path, *, dry_run: bool) -> None:
    if not path.exists():
        return
    if dry_run:
        print(f"  would remove: {path}")
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    print(f"  removed: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune migrated runtime from repo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from core.batman_mode import (
        data_reports_base,
        logs_base,
        runtime_root,
        secrets_root,
        workspace_root,
    )

    ws = workspace_root()
    print(f"Workspace: {ws}")
    print(f"Executed:  {runtime_root(ws)}")
    print(f"Logs:      {logs_base(ws)}")
    print(f"Data:      {data_reports_base(ws)}")
    print(f"Secrets:   {secrets_root(ws)}")
    print()

    print("Removing repo runtime trees:")
    for name in REMOVE_DIRS:
        _rm_tree(ROOT / name, dry_run=args.dry_run)

    print("\nPruning daily_test_execution outputs:")
    dte = ROOT / "daily_test_execution"
    for sub in DAILY_PRUNE_SUBDIRS:
        _rm_tree(dte / sub, dry_run=args.dry_run)
    for fname in DAILY_PRUNE_FILES:
        _rm_tree(dte / fname, dry_run=args.dry_run)

    print("\nPruning uat/deployed_positions runtime files:")
    if UAT_POSITIONS_DIR.exists():
        for item in UAT_POSITIONS_DIR.iterdir():
            if item.name == "README.md":
                continue
            _rm_tree(item, dry_run=args.dry_run)

    readme_uat = UAT_POSITIONS_DIR / "README.md"
    readme_data = ROOT / "data" / "README.md"
    if not args.dry_run:
        UAT_POSITIONS_DIR.mkdir(parents=True, exist_ok=True)
        readme_uat.write_text(README_UAT_POSITIONS, encoding="utf-8")
        ROOT.joinpath("data").mkdir(exist_ok=True)
        readme_data.write_text(README_DATA, encoding="utf-8")
        print(f"  wrote: {readme_uat}")
        print(f"  wrote: {readme_data}")

    print("\nDone. Repo should contain code + docs only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
