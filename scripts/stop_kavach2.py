#!/usr/bin/env python3
"""Stop Kavach 2.0 process (Phase-1 Kavach). Classic Kavach runner removed."""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    # Match run_kavach2.py only (not classic run_kavach.py — deleted).
    cmd = [
        "bash",
        "-lc",
        "pkill -f '[r]un_kavach2.py' || true; "
        "pgrep -af 'run_kavach2.py' || echo 'kavach2 not running'",
    ]
    r = subprocess.run(cmd)
    return 0 if r.returncode in (0, 1) else r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
