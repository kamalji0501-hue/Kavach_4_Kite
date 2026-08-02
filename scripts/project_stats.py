#!/usr/bin/env python3
"""Print Batman project size, structure, and complexity snapshot.

Usage:
  python scripts/project_stats.py
  python scripts/project_stats.py --full
  python scripts/project_stats.py --json
  python scripts/project_stats.py --top 20 --pytest
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.utils import get_venv_python

# Always skipped when walking the tree.
CACHE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    ".cursor",
}

# Skipped for "source" / Batman app views (runtime + vendor bulk).
RUNTIME_DIRS = {"logs", "data", "Dependencies"}

# Archived reference tree — excluded from Batman app totals.
REFERENCE_ROOTS = {"Dhan"}

DOC_EXTENSIONS = {".md", ".mdc"}
CODE_EXTENSIONS = {".py", ".bat", ".ps1", ".sh"}


@dataclass
class FolderStats:
    py_files: int = 0
    py_lines: int = 0
    all_files: int = 0


@dataclass
class Report:
    scope: str
    directories: int = 0
    files: int = 0
    python_files: int = 0
    python_lines: int = 0
    test_files: int = 0
    test_lines: int = 0
    doc_files: int = 0
    doc_lines: int = 0
    launcher_files: int = 0
    launcher_lines: int = 0
    by_top: dict[str, FolderStats] = field(default_factory=dict)
    largest_python: list[tuple[int, str]] = field(default_factory=list)
    runtime_logs_files: int = 0
    runtime_data_files: int = 0
    dhan_python_files: int = 0
    pytest_collected: int | None = None


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def _is_test_file(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def _is_reference(path: Path) -> bool:
    return bool(REFERENCE_ROOTS & set(path.parts))


def _should_skip_dir(name: str, exclude: set[str]) -> bool:
    return name in exclude


def _count_runtime_files(name: str) -> int:
    base = ROOT / name
    if not base.is_dir():
        return 0
    count = 0
    for _dirpath, _dirnames, filenames in os.walk(base):
        count += len(filenames)
    return count


def _collect_pytest_count() -> int | None:
    python = get_venv_python(ROOT)
    if not python.is_file():
        python = Path(sys.executable)
    try:
        proc = subprocess.run(
            [str(python), "-m", "pytest", "tests", "--collect-only"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    for line in reversed(combined.splitlines()):
        if " tests collected" in line:
            try:
                return int(line.strip().split()[0])
            except ValueError:
                return None
    return None


def build_report(
    *,
    scope: str,
    exclude_dirs: set[str],
    exclude_reference: bool,
    top_n: int,
) -> Report:
    report = Report(scope=scope)
    py_sizes: list[tuple[int, str]] = []

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d, exclude_dirs)]

        current = Path(dirpath)
        if any(part in exclude_dirs for part in current.parts):
            dirnames.clear()
            continue
        if exclude_reference and _is_reference(current):
            dirnames.clear()
            continue

        report.directories += 1

        for filename in filenames:
            fp = current / filename
            if any(part in exclude_dirs for part in fp.parts):
                continue
            if exclude_reference and _is_reference(fp):
                continue

            report.files += 1
            rel = fp.relative_to(ROOT)
            top = rel.parts[0] if rel.parts else "(root)"
            bucket = report.by_top.setdefault(top, FolderStats())
            bucket.all_files += 1

            ext = fp.suffix.lower()
            if ext == ".py":
                lines = _line_count(fp)
                report.python_files += 1
                report.python_lines += lines
                bucket.py_files += 1
                bucket.py_lines += lines
                py_sizes.append((lines, str(rel).replace("\\", "/")))

                if _is_test_file(fp):
                    report.test_files += 1
                    report.test_lines += lines

            elif ext in DOC_EXTENSIONS:
                lines = _line_count(fp)
                report.doc_files += 1
                report.doc_lines += lines

            elif ext in {".bat", ".ps1"}:
                lines = _line_count(fp)
                report.launcher_files += 1
                report.launcher_lines += lines

    report.largest_python = sorted(py_sizes, reverse=True)[:top_n]
    report.runtime_logs_files = _count_runtime_files("logs")
    report.runtime_data_files = _count_runtime_files("data")

    dhan_root = ROOT / "Dhan"
    if dhan_root.is_dir():
        for fp in dhan_root.rglob("*.py"):
            if any(part in exclude_dirs for part in fp.parts):
                continue
            report.dhan_python_files += 1

    return report


def _exclude_for_scope(scope: str) -> tuple[set[str], bool]:
    if scope == "full":
        return set(CACHE_DIRS), False
    if scope == "source":
        return CACHE_DIRS | RUNTIME_DIRS, False
    # batman (default): app code only
    return CACHE_DIRS | RUNTIME_DIRS, True


def _human(report: Report, *, include_pytest: bool) -> None:
    prod_files = report.python_files - report.test_files
    prod_lines = report.python_lines - report.test_lines
    pct = (100.0 * report.test_lines / report.python_lines) if report.python_lines else 0.0

    print(f"=== Batman project stats ({report.scope}) ===\n")
    print(f"Root: {ROOT}\n")

    print("Structure")
    print(f"  Directories:  {report.directories:,}")
    print(f"  Files:        {report.files:,}")
    print()

    print("Python")
    print(f"  Total:        {report.python_files:,} files / {report.python_lines:,} lines")
    print(f"  Production:   {prod_files:,} files / {prod_lines:,} lines")
    print(f"  Tests:        {report.test_files:,} files / {report.test_lines:,} lines ({pct:.1f}%)")
    print()

    print("Docs & launchers")
    print(f"  Markdown:     {report.doc_files:,} files / {report.doc_lines:,} lines")
    print(f"  .bat / .ps1:  {report.launcher_files:,} files / {report.launcher_lines:,} lines")
    print(
        f"  App + docs:   ~{report.python_lines + report.doc_lines:,} lines (Python + markdown)"
    )
    print()

    if report.scope != "full":
        print("Runtime artifacts (not in scope above)")
        print(f"  logs/:        {report.runtime_logs_files:,} files")
        print(f"  data/:        {report.runtime_data_files:,} files")
        print()

    if report.dhan_python_files and report.scope == "batman":
        print("Reference (excluded from Batman app totals)")
        print(f"  Dhan/:        {report.dhan_python_files:,} .py files (archive; may include venv)")
        print()

    rows = [
        (top, stats.py_files, stats.py_lines)
        for top, stats in report.by_top.items()
        if stats.py_lines > 0
    ]
    if rows:
        print("Python LOC by top-level folder")
        for top, py_count, py_lines in sorted(rows, key=lambda r: -r[2]):
            print(f"  {top:22} {py_count:4} .py  {py_lines:7,} lines")
        print()

    if report.largest_python:
        print("Largest Python files")
        for lines, rel in report.largest_python:
            print(f"  {lines:5,}  {rel}")
        print()

    if include_pytest and report.pytest_collected is not None:
        print(f"Pytest:         {report.pytest_collected:,} tests collected")
        print()

    print("Scopes:  batman (default) | source | full")
    print("Re-run:  python scripts/project_stats.py [--full] [--pytest] [--top N] [--json]")


def _serialize_report(report: Report) -> dict:
    data = asdict(report)
    data["by_top"] = {k: asdict(v) for k, v in report.by_top.items()}
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print lines-of-code, file counts, and structure for the Batman repo."
    )
    parser.add_argument(
        "--scope",
        choices=("batman", "source", "full"),
        default="batman",
        help="batman=app excl. Dhan (default); source=excl. logs/data; full=entire tree",
    )
    parser.add_argument(
        "--full",
        action="store_const",
        const="full",
        dest="scope",
        help="Shorthand for --scope full",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=12,
        metavar="N",
        help="Number of largest Python files to list (default: 12)",
    )
    parser.add_argument(
        "--pytest",
        action="store_true",
        help="Also run pytest --collect-only and report test count",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON on stdout",
    )
    args = parser.parse_args()

    exclude_dirs, exclude_reference = _exclude_for_scope(args.scope)
    report = build_report(
        scope=args.scope,
        exclude_dirs=exclude_dirs,
        exclude_reference=exclude_reference,
        top_n=max(1, args.top),
    )

    if args.pytest:
        report.pytest_collected = _collect_pytest_count()

    if args.json:
        print(json.dumps(_serialize_report(report), indent=2))
    else:
        _human(report, include_pytest=args.pytest)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
