#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

FORCE="$1"

echo "Stopping any old DRISHTI instances..."
"$DIR/../Stop Bots/stop Drishti.sh" silent
sleep 2

echo "Verifying DRISHTI is stopped..."
"$DIR/_preflight_start.sh" drishti "$FORCE"
if [ $? -ne 0 ]; then
    echo "START ABORTED."
    exit 1
fi

echo "Starting DRISHTI..."
export BATMAN_LAUNCHED_VIA_BAT=1
"$PY" run_drishti.py
