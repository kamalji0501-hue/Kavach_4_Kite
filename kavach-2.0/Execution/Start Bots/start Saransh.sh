#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

FORCE="$1"

echo "Stopping any old SARANSH instances..."
"$DIR/../Stop Bots/stop Saransh.sh" silent
sleep 2

echo "Verifying SARANSH is stopped..."
"$DIR/_preflight_start.sh" saransh "$FORCE"
if [ $? -ne 0 ]; then
    echo "START ABORTED."
    exit 1
fi

echo "Starting SARANSH..."
export BATMAN_LAUNCHED_VIA_BAT=1
"$PY" run_saransh.py
