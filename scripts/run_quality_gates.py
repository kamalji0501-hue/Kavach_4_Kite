# Run all Batman quality gates (agent-friendly one-shot)
# Usage: .venv\Scripts\python.exe scripts\run_quality_gates.py
# Exit 0 = all pass; non-zero = first failure

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.utils import get_venv_python
PYTHON = get_venv_python(ROOT)

GATES: list[tuple[str, list[str]]] = [
    ("ruff", ["-m", "ruff", "check", "."]),
    ("black", ["-m", "black", "--check", "."]),
    ("mypy", ["-m", "mypy", "core", "modules", "bat_telegram"]),
    ("pytest", ["-m", "pytest", "tests", "-q", "--tb=short"]),
]


def run_gate(name: str, args: list[str]) -> int:
    print(f"\n=== {name} ===", flush=True)
    result = subprocess.run([str(PYTHON), *args], cwd=ROOT)
    if result.returncode != 0:
        print(f"\nFAIL: {name} (exit {result.returncode})", flush=True)
    else:
        print(f"PASS: {name}", flush=True)
    return result.returncode


def main() -> int:
    if not PYTHON.is_file():
        print(f"Missing venv Python: {PYTHON}", file=sys.stderr)
        return 1

    for name, args in GATES:
        code = run_gate(name, args)
        if code != 0:
            return code

    print("\nAll quality gates passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
