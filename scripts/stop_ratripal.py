#!/usr/bin/env python3
"""Stop all run_ratripal.py processes, close launcher CMD windows, remove lock."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.batman_mode import bot_lock_path
from scripts.stop_bot_common import stop_bot_instance


def main() -> int:
    silent = "--silent" in sys.argv
    # Root wrapper chdirs into kavach-2.0; lock lives under mode data dir via batman_mode.
    lock_root = ROOT / "kavach-2.0" if (ROOT / "kavach-2.0").is_dir() else ROOT
    return stop_bot_instance(
        runner_marker="run_ratripal.py",
        start_bat_marker="start Ratripal.bat",
        lock_path=bot_lock_path("ratripal", lock_root),
        bot_name="RATRIPAL",
        close_launcher_windows=not silent,
    )


if __name__ == "__main__":
    raise SystemExit(main())
