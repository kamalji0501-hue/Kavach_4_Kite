#!/bin/bash
# LEGACY — old KAVACH (v1) is a past project. Do not start it for Phase 1.
# Use KAVACH 2.0 instead:
#   Execution/Start Bots/start Kavach2.sh
#
# Original launcher body commented out on purpose.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

echo "BLOCKED: legacy KAVACH (v1) is retired."
echo "Start KAVACH 2.0 with: Execution/Start Bots/start Kavach2.sh"
exit 1

# FORCE="$1"
# echo "Stopping any old KAVACH instances..."
# "$DIR/../Stop Bots/stop Kavach.sh" silent
# sleep 2
# echo "Verifying KAVACH is stopped..."
# "$DIR/_preflight_start.sh" kavach "$FORCE"
# if [ $? -ne 0 ]; then
#     echo "START ABORTED."
#     exit 1
# fi
# echo "Starting KAVACH..."
# export BATMAN_LAUNCHED_VIA_BAT=1
# PY=".venv/bin/python"
# if [ ! -f "$PY" ]; then PY=".venv/Scripts/python.exe"; fi
# "$PY" run_kavach.py
