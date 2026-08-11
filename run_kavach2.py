#!/usr/bin/env python3
"""Phase 1 launcher wrapper — runs Kavach 2.0 from the kavach-2.0 sub-project."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KAVACH2_ROOT = Path(__file__).resolve().parent / "kavach-2.0"
if not _KAVACH2_ROOT.is_dir():
    raise SystemExit(f"Kavach 2.0 sub-project not found: {_KAVACH2_ROOT}")

_PARENT = _KAVACH2_ROOT.parent
os.chdir(_KAVACH2_ROOT)
# Parent first so shared core (telegram_credentials, etc.) wins over incomplete kavach-2.0/core.
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
if str(_KAVACH2_ROOT) not in sys.path:
    sys.path.insert(0, str(_KAVACH2_ROOT))

from run_kavach2 import main

if __name__ == "__main__":
    main()
