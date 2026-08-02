#!/usr/bin/env python3
"""Stop all run_kavach.py processes, close launcher CMD windows, remove lock."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.batman_mode import kavach_lock_path
from scripts.stop_bot_common import stop_bot_instance


def main() -> int:
    silent = "--silent" in sys.argv
    return stop_bot_instance(
        runner_marker="run_kavach.py",
        start_bat_marker="start Kavach.bat",
        lock_path=kavach_lock_path(ROOT),
        bot_name="KAVACH",
        close_launcher_windows=not silent,
    )


if __name__ == "__main__":
    raise SystemExit(main())
