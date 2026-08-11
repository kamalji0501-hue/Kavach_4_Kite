#!/usr/bin/env bash
set -euo pipefail
RC=/home/ubuntu/rahul_Changes
LOG_DIR=/home/ubuntu/Trading_Runtime_Rahul/Logs/uat/runtime/ops
mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/ensure_kavach2.log" 2>&1
echo "==== $(date -Is) ===="
cd "$RC"
exec "$RC/.venv/bin/python" "$RC/scripts/ensure_kavach2_uptime.py"
