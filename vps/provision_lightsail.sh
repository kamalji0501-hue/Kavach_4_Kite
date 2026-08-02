#!/usr/bin/env bash
# Provision AWS Lightsail instance for Batman (Mumbai / ap-south-1).
# Requires: AWS CLI v2 configured (aws configure) OR env AWS_ACCESS_KEY_ID/SECRET.
#
# Usage:
#   bash vps/provision_lightsail.sh
#   bash vps/provision_lightsail.sh --status-only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATUS_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --status-only) STATUS_ONLY=1 ;;
  esac
done

ENV_FILE="$SCRIPT_DIR/deploy.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

REGION="${VPS_REGION:-ap-south-1}"
NAME="${LIGHTSAIL_INSTANCE_NAME:-batman-algo-uat}"
BLUEPRINT="${LIGHTSAIL_BLUEPRINT:-ubuntu_24_04}"
BUNDLE="${LIGHTSAIL_BUNDLE:-medium_3_0}"
STATUS_FILE="$SCRIPT_DIR/lightsail.STATUS"

if ! command -v aws >/dev/null 2>&1; then
  cat > "$STATUS_FILE" <<EOF
status: BLOCKED_NO_AWS_CLI
region: $REGION
instance_name: $NAME
action: Install AWS CLI v2, run 'aws configure', then re-run this script.
manual_console: https://lightsail.aws.amazon.com/ls/webapp/${REGION}/instances
manual_steps: |
  1. Create instance: Ubuntu 24.04, 4 GB / 2 vCPU (medium), Mumbai
  2. Create + attach Static IP
  3. Download default key → ~/.ssh/LightsailDefaultKey-ap-south-1.pem ; chmod 400
  4. Copy vps/deploy.env.example → vps/deploy.env ; set VPS_HOST + VPS_SSH_KEY + VPS_STATIC_IP
  5. bash vps/deploy_to_vps.sh
EOF
  echo "AWS CLI not found. Wrote $STATUS_FILE with console steps."
  cat "$STATUS_FILE"
  exit 0
fi

if ! aws sts get-caller-identity --region "$REGION" >/dev/null 2>&1; then
  cat > "$STATUS_FILE" <<EOF
status: BLOCKED_NO_AWS_CREDENTIALS
region: $REGION
action: Run 'aws configure' (or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY), then re-run.
EOF
  echo "AWS credentials missing. Wrote $STATUS_FILE"
  cat "$STATUS_FILE"
  exit 0
fi

if [[ "$STATUS_ONLY" -eq 1 ]]; then
  aws lightsail get-instance --instance-name "$NAME" --region "$REGION" 2>/dev/null \
    || echo "Instance $NAME not found in $REGION"
  exit 0
fi

if aws lightsail get-instance --instance-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Instance $NAME already exists."
else
  echo "Creating Lightsail instance $NAME ($BUNDLE / $BLUEPRINT) in $REGION…"
  aws lightsail create-instances \
    --instance-names "$NAME" \
    --availability-zone "${REGION}a" \
    --blueprint-id "$BLUEPRINT" \
    --bundle-id "$BUNDLE" \
    --region "$REGION"
  echo "Waiting for instance to become running…"
  for _ in $(seq 1 60); do
    STATE=$(aws lightsail get-instance --instance-name "$NAME" --region "$REGION" \
      --query 'instance.state.name' --output text 2>/dev/null || echo pending)
    echo "  state=$STATE"
    [[ "$STATE" == "running" ]] && break
    sleep 10
  done
fi

PUBLIC_IP=$(aws lightsail get-instance --instance-name "$NAME" --region "$REGION" \
  --query 'instance.publicIpAddress' --output text)

STATIC_NAME="${NAME}-static"
if ! aws lightsail get-static-ip --static-ip-name "$STATIC_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Allocating static IP $STATIC_NAME…"
  aws lightsail allocate-static-ip --static-ip-name "$STATIC_NAME" --region "$REGION"
fi
# Attach if not already
aws lightsail attach-static-ip --static-ip-name "$STATIC_NAME" --instance-name "$NAME" --region "$REGION" 2>/dev/null || true
STATIC_IP=$(aws lightsail get-static-ip --static-ip-name "$STATIC_NAME" --region "$REGION" \
  --query 'staticIp.ipAddress' --output text)

# Open SSH (Lightsail default usually open; ensure)
aws lightsail open-instance-public-ports \
  --instance-name "$NAME" \
  --port-info fromPort=22,toPort=22,protocol=tcp \
  --region "$REGION" 2>/dev/null || true

cat > "$STATUS_FILE" <<EOF
status: READY
region: $REGION
instance_name: $NAME
public_ip: $PUBLIC_IP
static_ip: $STATIC_IP
ssh_user: ubuntu
next: |
  1. Download key from Lightsail console if needed → chmod 400 ~/.ssh/LightsailDefaultKey-ap-south-1.pem
  2. cp vps/deploy.env.example vps/deploy.env
  3. Set VPS_HOST=$STATIC_IP  VPS_STATIC_IP=$STATIC_IP  VPS_SSH_KEY=~/.ssh/LightsailDefaultKey-ap-south-1.pem
  4. bash vps/deploy_to_vps.sh
  5. .venv/bin/python scripts/vps_smoke_live_ticks.py --remote
EOF

# Patch deploy.env if present
if [[ -f "$ENV_FILE" ]]; then
  grep -q '^VPS_HOST=' "$ENV_FILE" && sed -i "s|^VPS_HOST=.*|VPS_HOST=$STATIC_IP|" "$ENV_FILE" || echo "VPS_HOST=$STATIC_IP" >> "$ENV_FILE"
  grep -q '^VPS_STATIC_IP=' "$ENV_FILE" && sed -i "s|^VPS_STATIC_IP=.*|VPS_STATIC_IP=$STATIC_IP|" "$ENV_FILE" || echo "VPS_STATIC_IP=$STATIC_IP" >> "$ENV_FILE"
fi

echo "OK: Lightsail ready — static IP $STATIC_IP"
cat "$STATUS_FILE"
