#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/.."
cd "$ROOT"

if [ ! -f ".venv/bin/python" ] && [ ! -f ".venv/Scripts/python.exe" ]; then
    echo "ERROR: Virtual environment not found."
    exit 1
fi

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

echo "Setting Batman mode to Prod..."
"$PY" scripts/set_batman_mode.py prod
