#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

FORCE="$1"

echo "Stopping any old KAVACH instances..."
"$DIR/../Stop Bots/stop Kavach.sh" silent
sleep 2

echo "Verifying KAVACH is stopped..."
"$DIR/_preflight_start.sh" kavach "$FORCE"
if [ $? -ne 0 ]; then
    echo "START ABORTED."
    exit 1
fi

echo "Starting KAVACH..."
export BATMAN_LAUNCHED_VIA_BAT=1
"$PY" run_kavach2.py
