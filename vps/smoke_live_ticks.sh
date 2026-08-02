#!/usr/bin/env bash
# Thin wrapper around scripts/vps_smoke_live_ticks.py
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/vps_smoke_live_ticks.py" "$@"
