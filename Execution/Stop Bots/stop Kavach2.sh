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
    "$PY" scripts/stop_kavach2.py --silent
else
    "$PY" scripts/stop_kavach2.py
fi

"$DIR/_verify_stopped.sh" kavach2
