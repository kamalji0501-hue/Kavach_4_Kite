#!/usr/bin/env bash
# Stage B — production cutover checklist (prints + writes status; does NOT flip mode
# unless you pass --apply-prod AFTER confirming Dhan static-IP whitelist).
#
# Usage:
#   bash vps/prod_cutover_checklist.sh
#   bash vps/prod_cutover_checklist.sh --apply-prod   # only after whitelist confirmed
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APPLY=0
for arg in "$@"; do
  [[ "$arg" == "--apply-prod" ]] && APPLY=1
done

ENV_FILE="$SCRIPT_DIR/deploy.env"
STATIC_IP=""
HOST=""
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  STATIC_IP="${VPS_STATIC_IP:-}"
  HOST="${VPS_HOST:-}"
fi

STATUS="$SCRIPT_DIR/prod_cutover.STATUS"
{
  echo "generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "stage: B_PROD_CUTOVER"
  echo "vps_host: ${HOST:-unset}"
  echo "static_ip: ${STATIC_IP:-unset}"
  echo ""
  echo "checklist:"
  echo "  [ ] 1. Stage A UAT always-on stable for several market sessions"
  echo "  [ ] 2. Dhan console: whitelist static IP ${STATIC_IP:-<set VPS_STATIC_IP>}"
  echo "  [ ] 3. Fresh Dhan JWT on VPS (DRISHTI / access_token.json)"
  echo "  [ ] 4. Confirm batman-phase1.target active on VPS"
  echo "  [ ] 5. Run: Mode Set-Prod on VPS (or --apply-prod below)"
  echo "  [ ] 6. Supervised Register + one ATO cycle observation"
  echo "  [ ] 7. Go/no-go: full-session ws_ltp log, no false off-hours stale"
  echo ""
} > "$STATUS"

echo "=== Stage B production cutover checklist ==="
cat "$STATUS"

if [[ "$APPLY" -eq 0 ]]; then
  echo "Dry checklist only. When ready on the VPS:"
  echo "  ssh … 'cd ~/batman-algo && .venv/bin/python scripts/set_batman_mode.py prod && sudo systemctl restart batman-phase1.target'"
  echo "Or re-run: bash vps/prod_cutover_checklist.sh --apply-prod"
  exit 0
fi

if [[ -z "$HOST" || "$HOST" == "0.0.0.0" ]]; then
  echo "BLOCKED: VPS_HOST not set in vps/deploy.env — cannot apply prod remotely."
  echo "status: BLOCKED_NO_VPS" >> "$STATUS"
  exit 1
fi

KEY_PATH="${VPS_SSH_KEY/#\~/$HOME}"
: "${VPS_USER:=ubuntu}"
: "${BATMAN_ROOT:=/home/ubuntu/batman-algo}"

read -r -p "Confirm Dhan has whitelisted static IP ${STATIC_IP:-UNKNOWN}? [yes/NO] " ans
if [[ "$ans" != "yes" ]]; then
  echo "Aborted — whitelist not confirmed."
  exit 1
fi

ssh -i "$KEY_PATH" -o IdentitiesOnly=yes "${VPS_USER}@${HOST}" bash -s <<REMOTE
set -euo pipefail
cd '$BATMAN_ROOT'
.venv/bin/python scripts/set_batman_mode.py prod
sudo systemctl restart batman-phase1.target
sleep 8
systemctl is-active batman-drishti batman-kavach2 batman-jagran batman-saransh
.venv/bin/python -c "from core.batman_mode import get_mode; print('mode', get_mode())"
REMOTE

echo "status: PROD_APPLIED" >> "$STATUS"
echo "OK: prod mode applied on VPS. Supervise first live session."
