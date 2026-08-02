#!/usr/bin/env python3

"""Stop all run_jagran.py processes, close launcher CMD windows, remove lock."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:

    sys.path.insert(0, str(ROOT))


from core.bot_process_status import bot_lock_path

from scripts.stop_bot_common import stop_bot_instance


def main() -> int:

    silent = "--silent" in sys.argv

    return stop_bot_instance(
        runner_marker="run_jagran.py",
        start_bat_marker="start Jagran.bat",
        lock_path=bot_lock_path("jagran", root=ROOT),
        bot_name="JAGRAN",
        close_launcher_windows=not silent,
    )


if __name__ == "__main__":

    raise SystemExit(main())
