#!/usr/bin/env python3
"""Keep Datafeedbot + Kavach2 + Feeder LTP healthy during market hours."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
KAVACH = ROOT / "kavach-2.0"
sys.path.insert(0, str(KAVACH))
os.chdir(KAVACH)
os.environ.setdefault("BATMAN_MODE", "prod")

from core.feeder_ipc import feeder_socket_ready  # noqa: E402
from core.nifty_ltp_feed import cache_consumer_status, read_nifty_ltp_cache  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("ensure_market_stack")

IST = ZoneInfo("Asia/Kolkata")
STATE_PATH = Path(
    os.environ.get(
        "MARKET_STACK_STATE",
        "/home/ubuntu/Trading_Runtime_Rahul/Data/data/shared/market_stack_ensure_state.json",
    )
)
COOLDOWN_PATH = Path(
    os.environ.get(
        "MARKET_STACK_COOLDOWN",
        "/home/ubuntu/Trading_Runtime_Rahul/Data/data/shared/market_stack_restart_cooldown.json",
    )
)
BATMAN_STATE = Path(
    "/home/ubuntu/Trading_Runtime_Rahul/Data/data/prod/batman_state.json"
)

DATAFEEDBOT_SERVICE = os.environ.get("DATAFEEDBOT_SERVICE", "datafeedbot.service")
KAVACH2_SERVICE = os.environ.get("BATMAN_KAVACH2_SERVICE", "batman-kavach2.service")

MARKET_OPEN = (9, 10)
MARKET_CLOSE = (15, 35)
STALE_CACHE_SECONDS = float(os.environ.get("MARKET_STACK_STALE_SECONDS", "20"))
RESTART_COOLDOWN_SECONDS = int(os.environ.get("MARKET_STACK_RESTART_COOLDOWN", "300"))


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def service_active(name: str) -> bool:
    return _run(["systemctl", "is-active", name]).stdout.strip() == "active"


def ensure_service(name: str) -> str:
    if service_active(name):
        return "already_active"
    log.warning("%s inactive — starting", name)
    cp = _run(["sudo", "-n", "systemctl", "start", name])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or f"start failed: {name}")
    for _ in range(20):
        if service_active(name):
            return "started"
        time.sleep(1)
    raise RuntimeError(f"{name} still not active after start")


def restart_service(name: str, reason: str) -> str:
    log.warning("Restarting %s — %s", name, reason)
    cp = _run(["sudo", "-n", "systemctl", "restart", name])
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or f"restart failed: {name}")
    for _ in range(30):
        if service_active(name):
            return "restarted"
        time.sleep(1)
    raise RuntimeError(f"{name} still not active after restart")


def in_market_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    start = datetime.now(IST).replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0).time()
    end = datetime.now(IST).replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0).time()
    return start <= t <= end


def cooldown_ready(service: str) -> bool:
    try:
        raw = json.loads(COOLDOWN_PATH.read_text())
    except Exception:
        return True
    last = float(raw.get(service, 0) or 0)
    return (time.time() - last) >= RESTART_COOLDOWN_SECONDS


def mark_restart(service: str) -> None:
    COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, float] = {}
    if COOLDOWN_PATH.exists():
        with contextlib.suppress(Exception):
            raw = json.loads(COOLDOWN_PATH.read_text())
    raw[service] = time.time()
    COOLDOWN_PATH.write_text(json.dumps(raw, indent=2) + "\n")


import contextlib  # noqa: E402 — placed after use in mark_restart helper setup


def read_ops_flags() -> dict[str, object]:
    out: dict[str, object] = {}
    try:
        st = json.loads(BATMAN_STATE.read_text())
        out["deployment_confirmed"] = bool(st.get("deployment", {}).get("confirmed"))
        out["algo_paused"] = bool(st.get("algo", {}).get("paused"))
        ato = st.get("ato", {})
        out["pe_side_halted"] = bool(ato.get("pe_side_halted"))
        out["pe_halt_reason"] = ato.get("pe_halt_reason")
        out["manage_sides"] = ato.get("manage_sides")
    except Exception as exc:
        out["batman_state_error"] = str(exc)
    return out


def _ato_summary() -> dict:
    try:
        from core.ato_readiness import ato_readiness_snapshot

        snap = ato_readiness_snapshot()
        return {
            "armed": snap.get("armed"),
            "summary_line": snap.get("summary_line"),
            "hard_blocked_reasons": snap.get("hard_blocked_reasons"),
            "checked_at": snap.get("checked_at"),
        }
    except Exception as exc:
        return {"error": str(exc)}


def main() -> int:
    now = datetime.now(IST)
    status: dict[str, object] = {
        "ts": now.isoformat(timespec="seconds"),
        "in_market_window": in_market_window(now),
        "services": {},
        "feed": {},
        "ops": read_ops_flags(),
        "actions": [],
        "ok": True,
    }

    if not status["in_market_window"]:
        status["note"] = "outside market window — service check only"
        for label, svc in (("datafeedbot", DATAFEEDBOT_SERVICE), ("kavach2", KAVACH2_SERVICE)):
            try:
                status["services"][label] = ensure_service(svc)
            except Exception as exc:
                status["services"][label] = f"error: {exc}"
                status["ok"] = False
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(status, indent=2) + "\n")
        print(json.dumps(status))
        return 0 if status["ok"] else 1

    try:
        status["services"]["datafeedbot"] = ensure_service(DATAFEEDBOT_SERVICE)
        status["services"]["kavach2"] = ensure_service(KAVACH2_SERVICE)
    except Exception as exc:
        status["ok"] = False
        status["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("service ensure failed")

    ok_cache, detail = cache_consumer_status()
    snap = read_nifty_ltp_cache()
    status["feed"] = {
        "cache_ok": ok_cache,
        "detail": detail,
        "socket_ready": feeder_socket_ready(),
        "collector": getattr(snap, "collector", None) if snap else None,
        "source": getattr(snap, "source", None) if snap else None,
        "age_seconds": round(snap.age_seconds(), 2) if snap else None,
    }

    if snap and snap.age_seconds() > STALE_CACHE_SECONDS and service_active(DATAFEEDBOT_SERVICE):
        if cooldown_ready(DATAFEEDBOT_SERVICE):
            try:
                status["services"]["datafeedbot"] = restart_service(
                    DATAFEEDBOT_SERVICE,
                    f"NIFTY cache stale age={snap.age_seconds():.0f}s",
                )
                status["actions"].append("restarted_datafeedbot_stale_cache")
                mark_restart(DATAFEEDBOT_SERVICE)
                time.sleep(3)
                ok_cache, detail = cache_consumer_status()
                status["feed"]["after_restart"] = {"cache_ok": ok_cache, "detail": detail}
            except Exception as exc:
                status["ok"] = False
                status["feed"]["restart_error"] = str(exc)
                log.exception("datafeedbot restart failed")
        else:
            status["feed"]["restart_skipped"] = "cooldown"

    if not ok_cache:
        status["ok"] = False
        log.warning("NIFTY cache not ready: %s", detail)

    if not status["feed"].get("socket_ready"):
        status["ok"] = False
        log.warning("Feeder IPC socket not ready")

    ops = status["ops"]
    if ops.get("algo_paused"):
        log.info("Note: algo is paused (operator choice — not auto-resuming)")
    if ops.get("pe_side_halted"):
        log.warning("Note: PE side halted (%s) — operator action may be needed", ops.get("pe_halt_reason"))

    try:
        status["ato_readiness"] = _ato_summary()
    except Exception:
        pass
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status))
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
