#!/usr/bin/env bash
# Deploy Batman Algo tree to a remote VPS and enable Stage-A UAT always-on.
#
# Prerequisites:
#   1. Copy vps/deploy.env.example → vps/deploy.env and fill VPS_HOST + SSH key
#   2. Lightsail instance reachable via SSH
#
# Usage:
#   bash vps/deploy_to_vps.sh
#   bash vps/deploy_to_vps.sh --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "Usage: $0 [--dry-run]"
      exit 0
      ;;
  esac
done

ENV_FILE="$SCRIPT_DIR/deploy.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  echo "Copy deploy.env.example → deploy.env and set VPS_HOST / VPS_SSH_KEY."
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${VPS_HOST:?VPS_HOST required}"
: "${VPS_USER:=ubuntu}"
: "${VPS_SSH_KEY:?VPS_SSH_KEY required}"
: "${BATMAN_ROOT:=/home/ubuntu/batman-algo}"
: "${BATMAN_USER:=ubuntu}"
: "${BATMAN_MODE:=uat}"

KEY_PATH="${VPS_SSH_KEY/#\~/$HOME}"
if [[ ! -f "$KEY_PATH" ]]; then
  echo "ERROR: SSH key not found: $KEY_PATH"
  exit 1
fi

SSH=(ssh -i "$KEY_PATH" -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes "${VPS_USER}@${VPS_HOST}")
# Quote KEY_PATH so paths with spaces (e.g. "Batman Algo Files") work with rsync -e.
RSYNC_SSH="ssh -i \"$KEY_PATH\" -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes"

echo "=== Deploy Batman → ${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT} (mode=$BATMAN_MODE) ==="

# SAFETY: PNL Summary bot is local-only — never ship to the trading server.
# It lives outside this repo (Batman Algo Files/PNL summary). Refuse if present in tree.
EXCLUDES_FILE="$SCRIPT_DIR/rsync-excludes.txt"
if [[ -d "$REPO_ROOT/PNL summary" || -d "$REPO_ROOT/PNL_summary" || -d "$REPO_ROOT/pnl-summary" ]]; then
  echo "ERROR: PNL Summary bot tree found under BATMAN repo root."
  echo "       Remove it from $REPO_ROOT — that project must stay local only."
  exit 1
fi
if [[ -f "$REPO_ROOT/kite_client.py" ]]; then
  echo "ERROR: kite_client.py (PNL Summary fingerprint) found in repo root — local only."
  exit 1
fi
case "$REPO_ROOT" in
  *"PNL summary"*|*"PNL_summary"*|*"pnl-summary"*)
    echo "ERROR: REFUSING to deploy — REPO_ROOT points at PNL Summary: $REPO_ROOT"
    exit 1
    ;;
esac

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN: would rsync repo (exclusions applied) and remote-install systemd"
  echo "SSH probe…"
  "${SSH[@]}" 'echo OK remote=$(hostname); uname -a; free -h | head -2'
  exit 0
fi

# Ensure remote dirs (code + Trading_Runtime outside the code tree)
TR_ROOT="${TRADING_RUNTIME_ROOT:-/home/ubuntu/Trading_Runtime}"
"${SSH[@]}" "mkdir -p '$BATMAN_ROOT' \
  '$TR_ROOT'/{Logs,Data,Credentials,Temp,Cache,Backups,Health,Exports,Screenshots,Database,User,Config} \
  '$TR_ROOT'/Credentials/{config,Tokens,telegram/bots} \
  '$TR_ROOT'/Data/data/shared"

# Sync code (exclude heavy/runtime/secrets + PNL Summary local-only paths)
RSYNC_EXCLUDES=(
  --exclude '.venv/'
  --exclude '__pycache__/'
  --exclude '.git/'
  --exclude 'logs_runtime/'
  --exclude 'data_runtime/'
  --exclude 'secrets_runtime/'
  --exclude 'backtest_engine/cache/'
  --exclude 'kavach-2.0/backtest_engine/cache/'
  --exclude 'vps/deploy.env'
  --exclude '*.pyc'
  --exclude '.pytest_cache/'
  --exclude 'PNL summary/'
  --exclude 'PNL_summary/'
  --exclude 'pnl-summary/'
  --exclude 'kite_client.py'
  --exclude 'get_access_token.py'
)
if [[ -f "$EXCLUDES_FILE" ]]; then
  RSYNC_EXCLUDES+=(--exclude-from="$EXCLUDES_FILE")
fi

rsync -az --delete \
  "${RSYNC_EXCLUDES[@]}" \
  -e "$RSYNC_SSH" \
  "$REPO_ROOT/" "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/"

# Secrets → Trading_Runtime/Credentials (canonical) + in-repo fallback copies
TR_ROOT="${TRADING_RUNTIME_ROOT:-/home/ubuntu/Trading_Runtime}"
if [[ -f "$REPO_ROOT/config/.env" ]]; then
  scp -i "$KEY_PATH" -o IdentitiesOnly=yes \
    "$REPO_ROOT/config/.env" "${VPS_USER}@${VPS_HOST}:${TR_ROOT}/Credentials/config/.env"
  scp -i "$KEY_PATH" -o IdentitiesOnly=yes \
    "$REPO_ROOT/config/.env" "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/config/.env"
fi
# Prefer local Trading_Runtime credentials if present
LOCAL_TR="${LOCAL_TRADING_RUNTIME:-/home/kamalji0501e/Batman Algo Files/Trading_Runtime}"
if [[ -f "$LOCAL_TR/Credentials/config/.env" ]]; then
  scp -i "$KEY_PATH" -o IdentitiesOnly=yes \
    "$LOCAL_TR/Credentials/config/.env" "${VPS_USER}@${VPS_HOST}:${TR_ROOT}/Credentials/config/.env"
fi

for bot in drishti kavach kavach2 jagran saransh ratripal lakshmi go; do
  tok=""
  if [[ -f "$LOCAL_TR/Credentials/telegram/bots/$bot/token.env" ]]; then
    tok="$LOCAL_TR/Credentials/telegram/bots/$bot/token.env"
  elif [[ -f "$REPO_ROOT/telegram/bots/$bot/token.env" ]]; then
    tok="$REPO_ROOT/telegram/bots/$bot/token.env"
  elif [[ -f "$REPO_ROOT/kavach-2.0/telegram/bots/$bot/token.env" ]]; then
    tok="$REPO_ROOT/kavach-2.0/telegram/bots/$bot/token.env"
  elif [[ -f "$REPO_ROOT/GO/telegram/bots/$bot/token.env" ]]; then
    tok="$REPO_ROOT/GO/telegram/bots/$bot/token.env"
  fi
  if [[ -n "$tok" ]]; then
    "${SSH[@]}" "mkdir -p '$TR_ROOT/Credentials/telegram/bots/$bot' '$BATMAN_ROOT/telegram/bots/$bot'"
    scp -i "$KEY_PATH" -o IdentitiesOnly=yes "$tok" \
      "${VPS_USER}@${VPS_HOST}:${TR_ROOT}/Credentials/telegram/bots/$bot/token.env"
    # In-repo fallback for loader
    if [[ "$bot" == "kavach2" ]]; then
      "${SSH[@]}" "mkdir -p '$BATMAN_ROOT/kavach-2.0/telegram/bots/kavach2'"
      scp -i "$KEY_PATH" -o IdentitiesOnly=yes "$tok" \
        "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/kavach-2.0/telegram/bots/kavach2/token.env"
    elif [[ "$bot" == "go" ]]; then
      "${SSH[@]}" "mkdir -p '$BATMAN_ROOT/GO/telegram/bots/go'"
      scp -i "$KEY_PATH" -o IdentitiesOnly=yes "$tok" \
        "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/GO/telegram/bots/go/token.env"
    else
      scp -i "$KEY_PATH" -o IdentitiesOnly=yes "$tok" \
        "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/telegram/bots/$bot/token.env" 2>/dev/null || true
    fi
  fi
done

# Access token → Trading_Runtime shared data
TOK_SRC=""
for cand in \
  "$LOCAL_TR/Data/data/shared/access_token.json" \
  "$REPO_ROOT/data_runtime/data/shared/access_token.json" \
  "$HOME/Batman-Secrets/access_token.json"; do
  if [[ -f "$cand" ]]; then
    TOK_SRC="$cand"
    break
  fi
done
if [[ -n "$TOK_SRC" ]]; then
  "${SSH[@]}" "mkdir -p '$TR_ROOT/Data/data/shared'"
  scp -i "$KEY_PATH" -o IdentitiesOnly=yes "$TOK_SRC" \
    "${VPS_USER}@${VPS_HOST}:${TR_ROOT}/Data/data/shared/access_token.json"
fi

# VPS local_runtime.json (absolute Trading_Runtime — overrides any laptop paths from rsync)
"${SSH[@]}" bash -s <<EOF
set -euo pipefail
python3 - <<PY
import json
from pathlib import Path
tr = Path("$TR_ROOT")
root = Path("$BATMAN_ROOT")
payload = {
    "_comment": "VPS — runtime outside code tree",
    "logs_root": str(tr / "Logs"),
    "data_reports_root": str(tr / "Data"),
    "secrets_root": str(tr / "Credentials"),
}
for rel in ("config/local_runtime.json", "kavach-2.0/config/local_runtime.json"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
    print("wrote", p)
PY
EOF

# Monitor telegram env
if [[ -n "${VPS_MONITOR_TELEGRAM_ENV:-}" && -f "${VPS_MONITOR_TELEGRAM_ENV/#\~/$HOME}" ]]; then
  scp -i "$KEY_PATH" -o IdentitiesOnly=yes \
    "${VPS_MONITOR_TELEGRAM_ENV/#\~/$HOME}" \
    "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/vps_ops/telegram.env"
fi

# Remote bootstrap
"${SSH[@]}" bash -s <<REMOTE
set -euo pipefail
cd '$BATMAN_ROOT'
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
# UAT mode (Stage A)
.venv/bin/python scripts/set_batman_mode.py '$BATMAN_MODE'
# Ensure Trading_Runtime layout via path API
.venv/bin/python -c "from core.batman_mode import ensure_runtime_layout; print(ensure_runtime_layout())"
# Stop any ad-hoc phase1 processes before systemd takes over
.venv/bin/python scripts/phase1_stop_all.py --silent --no-popup 2>/dev/null || true
export BATMAN_ROOT='$BATMAN_ROOT'
export BATMAN_USER='$BATMAN_USER'
export VPS_OPS_DIR='$BATMAN_ROOT/vps_ops'
export TELEGRAM_ENV_PATH='$BATMAN_ROOT/vps_ops/telegram.env'
export PYTHON='$BATMAN_ROOT/.venv/bin/python'
bash vps/install_systemd.sh
sleep 5
systemctl is-active batman-drishti.service batman-kavach2.service batman-jagran.service batman-saransh.service || true
.venv/bin/python scripts/bot_status.py all || true
REMOTE

echo "OK: deploy finished. Trading_Runtime=$TR_ROOT"
echo "Next: bash vps/smoke_live_ticks.sh (or scripts/vps_smoke_live_ticks.py --remote)"
