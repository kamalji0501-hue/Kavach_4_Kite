#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

SILENT="$1"
if [ "$SILENT" = "silent" ]; then
    "$PY" scripts/phase1_stop_all.py --silent
else
    "$PY" scripts/phase1_stop_all.py
fi
