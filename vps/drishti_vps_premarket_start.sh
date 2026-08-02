#!/usr/bin/env bash
# AWS/VPS only — start DRISHTI before NSE session (default 09:00 IST weekdays).
set -euo pipefail

export TZ=Asia/Kolkata

if systemctl is-enabled --quiet batman-phase1.target 2>/dev/null; then
  sudo systemctl start batman-drishti.service
  echo "started batman-drishti.service"
else
  echo "SKIP: batman-phase1.target not enabled"
  exit 0
fi

LOG_EVENT="${HOME}/batman-ops/bin/log_event.sh"
if [[ -x "$LOG_EVENT" ]]; then
  "$LOG_EVENT" startup "drishti started pre-market (VPS schedule)"
fi
echo "OK: drishti_vps_premarket_start"
