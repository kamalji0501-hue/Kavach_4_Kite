#!/usr/bin/env bash
# Install IST cron for DRISHTI VPS policy (stop after 15:30, start 09:00 Mon–Fri).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATMAN_ROOT="${BATMAN_ROOT:-/home/ubuntu/rahul_Changes}"
OPS_BIN="${HOME}/batman-ops/bin"
mkdir -p "$OPS_BIN"

install -m 0755 "$SCRIPT_DIR/drishti_vps_after_close.sh" "$OPS_BIN/drishti_vps_after_close.sh"
install -m 0755 "$SCRIPT_DIR/drishti_vps_premarket_start.sh" "$OPS_BIN/drishti_vps_premarket_start.sh"

MARKER="# batman-drishti-vps-ist-schedule"
TMP=$(mktemp)
{
  crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v drishti_vps_after_close | grep -v drishti_vps_premarket_start | grep -v '^CRON_TZ=Asia/Kolkata' || true
  echo "CRON_TZ=Asia/Kolkata"
  echo "30 15 * * 1-5 $OPS_BIN/drishti_vps_after_close.sh >> $HOME/batman-ops/logs/drishti_vps_schedule.log 2>&1 $MARKER"
  echo "0 9 * * 1-5 $OPS_BIN/drishti_vps_premarket_start.sh >> $HOME/batman-ops/logs/drishti_vps_schedule.log 2>&1 $MARKER"
} > "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "Installed crontab (IST):"
crontab -l | grep -E 'drishti_vps|CRON_TZ' || true
echo "OK: install_drishti_vps_schedule"
