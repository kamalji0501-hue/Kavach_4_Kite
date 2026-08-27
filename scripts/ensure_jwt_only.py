#!/usr/bin/env python3
"""Silent Dhan JWT renew for Feeder + Kavach. Does not start Drishti."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/rahul_Changes/kavach-2.0")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from core.dhan_totp import needs_refresh, renew_and_save

    if not needs_refresh(root=ROOT):
        print("jwt_ok")
        return 0
    token = renew_and_save(root=ROOT)
    print(f"jwt_renewed len={len(token or '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
