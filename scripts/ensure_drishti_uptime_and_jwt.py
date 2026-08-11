#!/usr/bin/env python3
"""Ensure Drishti stays up and JWT is renewed before expiry (rahul_Changes track).

- Starts/restarts systemd unit ``batman-drishti.service`` if inactive.
- Renews Dhan JWT via TOTP when remaining hours <= threshold (default 6h).
- Never prints secrets.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("ensure_drishti")

SERVICE = os.environ.get("BATMAN_DRISHTI_SERVICE", "batman-drishti.service")
# Renew a bit earlier than in-process TotpRenewer (4h) so cron + in-bot both cover gaps.
REFRESH_HOURS = float(os.environ.get("DRISHTI_JWT_REFRESH_HOURS", "6"))
STATE_PATH = Path(
    os.environ.get(
        "DRISHTI_ENSURE_STATE",
        "/home/ubuntu/Trading_Runtime_Rahul/Data/data/shared/drishti_ensure_state.json",
    )
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def service_active() -> bool:
    cp = _run(["systemctl", "is-active", SERVICE])
    return cp.stdout.strip() == "active"


def ensure_service() -> str:
    if service_active():
        return "already_active"
    log.warning("%s inactive — starting", SERVICE)
    cp = _run(["sudo", "-n", "systemctl", "start", SERVICE])
    if cp.returncode != 0:
        # fallback without sudo if user perms allow
        cp2 = _run(["systemctl", "--user", "start", SERVICE])
        if cp.returncode != 0 and cp2.returncode != 0:
            raise RuntimeError(
                f"failed to start {SERVICE}: {cp.stderr.strip() or cp.stdout.strip()}"
            )
    # brief wait
    for _ in range(10):
        if service_active():
            return "started"
        import time

        time.sleep(1)
    if not service_active():
        raise RuntimeError(f"{SERVICE} still not active after start")
    return "started"


def ensure_jwt() -> dict:
    from core import dhan_totp
    from core.batman_mode import access_token_path
    from core.token_store import TokenStore

    # Clear inherited empty env overrides so dotenv wins
    for k in (
        "DHAN_CLIENT_CODE",
        "DHAN_PIN",
        "DHAN_TOTP_SECRET",
        "DHAN_TOTP_CONFIGURED_AT",
        "GO_TOTP_SECRET_MAX_DAYS",
    ):
        # do not pop if set correctly; only empty
        if os.environ.get(k, None) == "":
            os.environ.pop(k, None)

    creds = dhan_totp.load_credentials()
    out: dict = {
        "configured": bool(creds.configured),
        "auto_renew": dhan_totp.is_auto_renew_enabled(ROOT),
        "refreshed": False,
        "hours_left": None,
    }
    if not creds.configured:
        out["error"] = "totp_not_configured"
        return out

    # Force auto-renew ON for production keep-alive
    if not out["auto_renew"]:
        dhan_totp.set_auto_renew_enabled(True, ROOT)
        out["auto_renew"] = True
        out["auto_renew_forced_on"] = True

    store = TokenStore(path=access_token_path(ROOT))
    hours = store.effective_expires_in_hours()
    out["hours_left"] = hours
    need = hours is None or hours <= REFRESH_HOURS
    out["need_refresh"] = bool(need)
    if not need:
        return out

    log.info("JWT refresh needed (hours_left=%s threshold=%s)", hours, REFRESH_HOURS)
    token = dhan_totp.renew_and_save(ROOT)
    out["refreshed"] = True
    out["token_len"] = len(token)
    out["saved_at"] = json.loads(access_token_path(ROOT).read_text()).get("saved_at")
    # bounce Drishti so in-memory broker picks up if hot-reload missed
    log.info("restarting %s after JWT renew", SERVICE)
    _run(["sudo", "-n", "systemctl", "restart", SERVICE])
    out["service_restarted"] = True
    return out


def main() -> int:
    status = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "service": SERVICE,
    }
    try:
        status["service_action"] = ensure_service()
        status["jwt"] = ensure_jwt()
        # re-check service after possible restart
        status["service_active"] = service_active()
        ok = bool(status["service_active"]) and status["jwt"].get("configured")
        status["ok"] = ok
    except Exception as exc:
        status["ok"] = False
        status["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("ensure failed")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(status, indent=2) + "\n")
    log.info("ensure result ok=%s service_active=%s", status.get("ok"), status.get("service_active"))
    print(json.dumps(status))
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
