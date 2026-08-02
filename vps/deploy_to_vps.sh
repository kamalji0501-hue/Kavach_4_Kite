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

# Ensure remote dirs
"${SSH[@]}" "mkdir -p '$BATMAN_ROOT' '~/Batman Executed Data/Logs' '~/Batman Executed Data/Data and Reports' '~/Batman-Secrets'"

# Sync code (exclude heavy/runtime/secrets + PNL Summary local-only paths)
RSYNC_EXCLUDES=(
  --exclude '.venv/'
  --exclude '__pycache__/'
  --exclude '.git/'
  --exclude 'logs_runtime/'
  --exclude 'data_runtime/'
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

# Secrets: copy if present locally (never fail hard if missing — operator may scp later)
if [[ -f "$REPO_ROOT/config/.env" ]]; then
  scp -i "$KEY_PATH" -o IdentitiesOnly=yes \
    "$REPO_ROOT/config/.env" "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/config/.env"
fi
for bot in drishti kavach kavach2 jagran saransh; do
  tok="$REPO_ROOT/telegram/bots/$bot/token.env"
  if [[ -f "$tok" ]]; then
    "${SSH[@]}" "mkdir -p '$BATMAN_ROOT/telegram/bots/$bot'"
    scp -i "$KEY_PATH" -o IdentitiesOnly=yes "$tok" \
      "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/telegram/bots/$bot/token.env"
  fi
done

# Access token if present
TOK_SRC=""
for cand in \
  "$REPO_ROOT/data_runtime/data/shared/access_token.json" \
  "$HOME/Batman-Secrets/access_token.json"; do
  if [[ -f "$cand" ]]; then
    TOK_SRC="$cand"
    break
  fi
done
if [[ -n "$TOK_SRC" ]]; then
  "${SSH[@]}" "mkdir -p '$BATMAN_ROOT/data_runtime/data/shared'"
  scp -i "$KEY_PATH" -o IdentitiesOnly=yes "$TOK_SRC" \
    "${VPS_USER}@${VPS_HOST}:${BATMAN_ROOT}/data_runtime/data/shared/access_token.json"
fi

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

echo "OK: deploy finished. Next: bash vps/smoke_live_ticks.sh (or scripts/vps_smoke_live_ticks.py --remote)"
