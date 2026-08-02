#!/usr/bin/env python3
"""Smoke-check always-on UAT: bots + Nifty WS tick log coverage.

Local (default):
  .venv/bin/python scripts/vps_smoke_live_ticks.py

Remote (needs vps/deploy.env):
  .venv/bin/python scripts/vps_smoke_live_ticks.py --remote
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IST = ZoneInfo("Asia/Kolkata")


def _load_deploy_env() -> dict[str, str]:
    path = ROOT / "vps" / "deploy.env"
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _expand(p: str) -> str:
    return os.path.expanduser(p)


def check_local() -> dict:
    from core.batman_mode import get_mode, log_runtime_root, workspace_root
    from core.bot_process_status import BotRunState, classify_bot

    root = workspace_root()
    mode = get_mode(root)
    report: dict = {
        "where": "local",
        "mode": mode,
        "bots": {},
        "ok": True,
        "notes": [],
    }
    for robot in ("drishti", "kavach2", "jagran", "saransh"):
        st = classify_bot(robot, root=root)
        report["bots"][robot] = st.state.value
        if st.state is not BotRunState.RUNNING:
            report["ok"] = False
            report["notes"].append(f"{robot} not RUNNING ({st.state.value})")

    if mode != "uat":
        report["notes"].append(f"mode={mode} (Stage A expects uat)")

    # Tick log for today
    today = datetime.now(IST).date()
    logs = log_runtime_root(root)
    pattern = f"**/nifty_websocket_ltp/ws_ltp_{today.strftime('%Y%m%d')}.log"
    matches = sorted(logs.glob(pattern))
    report["tick_log"] = str(matches[-1]) if matches else None
    report["tick_lines"] = 0
    if matches:
        try:
            report["tick_lines"] = sum(1 for _ in matches[-1].open(encoding="utf-8", errors="ignore"))
        except OSError as exc:
            report["notes"].append(f"tick log read failed: {exc}")
            report["ok"] = False
    else:
        # Off-hours / weekend: prior session log is still useful proof
        prior = sorted(logs.glob("**/nifty_websocket_ltp/ws_ltp_*.log"))
        if prior:
            report["tick_log"] = str(prior[-1])
            report["tick_lines"] = sum(1 for _ in prior[-1].open(encoding="utf-8", errors="ignore"))
            report["notes"].append(
                f"No ws_ltp for {today}; using latest {prior[-1].name} ({report['tick_lines']} lines)"
            )
        else:
            report["ok"] = False
            report["notes"].append("No ws_ltp_*.log found under log_runtime_root")

    # During market hours expect growth; off-hours just require historical ticks exist
    now = datetime.now(IST)
    market = now.weekday() < 5 and (
        (now.hour > 9 or (now.hour == 9 and now.minute >= 15))
        and (now.hour < 15 or (now.hour == 15 and now.minute <= 30))
    )
    report["market_hours_ist"] = market
    if market and report["tick_lines"] < 10:
        report["ok"] = False
        report["notes"].append("Market hours but tick log nearly empty")

    return report


def check_remote() -> dict:
    env = _load_deploy_env()
    host = env.get("VPS_HOST", "")
    user = env.get("VPS_USER", "ubuntu")
    key = _expand(env.get("VPS_SSH_KEY", ""))
    root = env.get("BATMAN_ROOT", "/home/ubuntu/batman-algo")
    if not host or host in ("0.0.0.0", "127.0.0.1") or not key or not Path(key).is_file():
        return {
            "where": "remote",
            "ok": False,
            "notes": [
                "Remote smoke blocked: set VPS_HOST + VPS_SSH_KEY in vps/deploy.env "
                "(after Lightsail provision)."
            ],
        }
    remote_py = (
        f"cd {root} && .venv/bin/python scripts/vps_smoke_live_ticks.py --json"
    )
    cmd = [
        "ssh",
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "IdentitiesOnly=yes",
        f"{user}@{host}",
        remote_py,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        return {
            "where": "remote",
            "ok": False,
            "notes": [proc.stderr.strip() or proc.stdout.strip() or f"ssh exit {proc.returncode}"],
        }
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return {"where": "remote", "ok": False, "notes": ["bad JSON from remote", proc.stdout[-500:]]}


def main() -> int:
    parser = argparse.ArgumentParser(description="VPS/UAT live-tick smoke check")
    parser.add_argument("--remote", action="store_true", help="SSH to VPS from deploy.env")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    report = check_remote() if args.remote else check_local()
    out_path = ROOT / "vps" / "smoke_last_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report))
    else:
        print(json.dumps(report, indent=2))
        print(f"\nWrote {out_path}")
        if report.get("ok"):
            print("SMOKE: PASS")
        else:
            print("SMOKE: FAIL / BLOCKED — see notes")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
