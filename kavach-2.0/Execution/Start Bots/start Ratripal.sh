#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

FORCE="$1"

echo "Stopping any old RATRIPAL instances..."
"$DIR/../Stop Bots/stop Ratripal.sh" silent
sleep 2

echo "Verifying RATRIPAL is stopped..."
"$DIR/_preflight_start.sh" ratripal "$FORCE"
if [ $? -ne 0 ]; then
    echo "START ABORTED."
    exit 1
fi

echo "Starting RATRIPAL..."
export BATMAN_LAUNCHED_VIA_BAT=1
"$PY" run_ratripal.py
