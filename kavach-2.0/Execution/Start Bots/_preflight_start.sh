#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$DIR/../.."
cd "$ROOT"

PY=".venv/bin/python"
if [ ! -f "$PY" ]; then
    PY=".venv/Scripts/python.exe"
fi

BOT="$1"
FORCE="$2"

if [ "$FORCE" = "force" ]; then
    "$PY" scripts/ensure_bot_stopped.py "$BOT" --force
else
    "$PY" scripts/ensure_bot_stopped.py "$BOT"
fi
