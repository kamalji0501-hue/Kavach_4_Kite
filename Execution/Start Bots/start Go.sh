#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

FORCE="$1"

echo "Stopping any old GO instances..."
"$DIR/../Stop Bots/stop Go.sh" silent
sleep 2

echo "Verifying GO is stopped..."
"$DIR/_preflight_start.sh" go "$FORCE"
if [ $? -ne 0 ]; then
    echo "START ABORTED."
    exit 1
fi

echo "Starting GO..."
export BATMAN_LAUNCHED_VIA_BAT=1
"$PY" run_go.py
