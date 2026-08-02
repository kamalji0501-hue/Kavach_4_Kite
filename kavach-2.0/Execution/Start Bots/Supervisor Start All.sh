#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

echo "Starting all Phase 1 bots via supervisor (recommended)..."
"$PY" scripts/bot_supervisor.py start --force --success-popup
