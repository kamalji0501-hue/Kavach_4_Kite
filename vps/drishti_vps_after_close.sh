#!/usr/bin/env bash
# AWS/VPS only — after 15:30 IST stop DRISHTI (no off-hours UAT replay / overnight feed).
# Does not touch KAVACH2/JAGRAN/SARANSH. Install via vps/install_drishti_vps_schedule.sh
set -euo pipefail

BATMAN_ROOT="${BATMAN_ROOT:-/home/ubuntu/rahul_Changes}"
PARAMS="$BATMAN_ROOT/telegram/bots/drishti/params.json"
LOG_EVENT="${HOME}/batman-ops/bin/log_event.sh"

export TZ=Asia/Kolkata
now_hm=$(date +%H:%M)
# Safety: only act at/after 15:30 IST (cron should fire at 15:30)
if [[ "$now_hm" < "15:30" ]]; then
  echo "SKIP: before 15:30 IST (now=$now_hm)"
  exit 0
fi

if [[ -f "$PARAMS" ]] && command -v python3 >/dev/null 2>&1; then
  python3 - <<PY
import json
from pathlib import Path
p = Path("$PARAMS")
data = json.loads(p.read_text(encoding="utf-8"))
replay = data.setdefault("uat_market_replay", {})
replay["enabled"] = False
replay["force_uat_mode"] = False
p.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
print("locked uat_market_replay disabled in params.json")
PY
fi

if systemctl is-active --quiet batman-drishti.service 2>/dev/null; then
  sudo systemctl stop batman-drishti.service
  echo "stopped batman-drishti.service"
else
  echo "batman-drishti already stopped"
fi

if [[ -x "$LOG_EVENT" ]]; then
  "$LOG_EVENT" shutdown "drishti stopped post-15:30 IST (VPS policy — no off-hours UAT)"
fi

echo "OK: drishti_vps_after_close"
