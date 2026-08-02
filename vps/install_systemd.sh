#!/usr/bin/env bash
# Install Batman Phase-1 systemd units on this host (VPS or local Linux).
# Usage:
#   BATMAN_ROOT=/home/ubuntu/batman-algo BATMAN_USER=ubuntu bash vps/install_systemd.sh
#   bash vps/install_systemd.sh --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DRY_RUN=0
ENABLE_NOW=1
INSTALL_MONITOR=1

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-enable) ENABLE_NOW=0 ;;
    --no-monitor) INSTALL_MONITOR=0 ;;
    -h|--help)
      echo "Usage: $0 [--dry-run] [--no-enable] [--no-monitor]"
      exit 0
      ;;
  esac
done

BATMAN_ROOT="${BATMAN_ROOT:-$REPO_ROOT}"
BATMAN_USER="${BATMAN_USER:-$(whoami)}"
VPS_OPS_DIR="${VPS_OPS_DIR:-$BATMAN_ROOT/vps_ops}"
TELEGRAM_ENV_PATH="${TELEGRAM_ENV_PATH:-$VPS_OPS_DIR/telegram.env}"
PYTHON="${PYTHON:-$BATMAN_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "WARN: Python not found at $PYTHON (ok for dry-run with remote paths)"
  else
    echo "ERROR: Python not found at $PYTHON — create venv first."
    exit 1
  fi
fi

UNIT_SRC="$SCRIPT_DIR/systemd"
OUT_DIR="${SYSTEMD_OUT_DIR:-/tmp/batman-systemd-rendered}"
mkdir -p "$OUT_DIR"

render() {
  local src="$1"
  local dest="$2"
  sed \
    -e "s|__BATMAN_ROOT__|${BATMAN_ROOT}|g" \
    -e "s|__BATMAN_USER__|${BATMAN_USER}|g" \
    -e "s|__PYTHON__|${PYTHON}|g" \
    -e "s|__VPS_OPS_DIR__|${VPS_OPS_DIR}|g" \
    -e "s|__TELEGRAM_ENV_PATH__|${TELEGRAM_ENV_PATH}|g" \
    "$src" > "$dest"
  echo "rendered $(basename "$dest")"
}

UNITS=(
  batman-drishti.service
  batman-kavach2.service
  batman-jagran.service
  batman-saransh.service
  batman-phase1.target
)

for u in "${UNITS[@]}"; do
  render "$UNIT_SRC/$u" "$OUT_DIR/$u"
done

if [[ "$INSTALL_MONITOR" -eq 1 ]]; then
  render "$UNIT_SRC/vps-monitor-batman.service" "$OUT_DIR/vps-monitor-batman.service"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "=== DRY RUN — units written to $OUT_DIR ==="
  ls -la "$OUT_DIR"
  if command -v systemd-analyze >/dev/null 2>&1; then
    for u in "${UNITS[@]}"; do
      systemd-analyze verify "$OUT_DIR/$u" 2>&1 || true
    done
  fi
  echo "OK: dry-run complete"
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Installing system units requires sudo…"
  SUDO=sudo
else
  SUDO=
fi

for u in "${UNITS[@]}"; do
  $SUDO cp "$OUT_DIR/$u" "/etc/systemd/system/$u"
done
if [[ "$INSTALL_MONITOR" -eq 1 ]]; then
  $SUDO cp "$OUT_DIR/vps-monitor-batman.service" /etc/systemd/system/vps-monitor-batman.service
fi

# Passwordless restart for monitor (same pattern as vps_ops/sudoers-vps-monitor)
SUDOERS_TMP=$(mktemp)
cat > "$SUDOERS_TMP" <<EOF
${BATMAN_USER} ALL=NOPASSWD: /bin/systemctl restart batman-drishti.service
${BATMAN_USER} ALL=NOPASSWD: /bin/systemctl restart batman-kavach2.service
${BATMAN_USER} ALL=NOPASSWD: /bin/systemctl restart batman-jagran.service
${BATMAN_USER} ALL=NOPASSWD: /bin/systemctl restart batman-saransh.service
${BATMAN_USER} ALL=NOPASSWD: /bin/systemctl restart batman-phase1.target
EOF
$SUDO cp "$SUDOERS_TMP" /etc/sudoers.d/batman-vps-monitor
$SUDO chmod 440 /etc/sudoers.d/batman-vps-monitor
rm -f "$SUDOERS_TMP"

$SUDO systemctl daemon-reload

if [[ "$ENABLE_NOW" -eq 1 ]]; then
  $SUDO systemctl enable batman-phase1.target
  $SUDO systemctl start batman-phase1.target
  if [[ "$INSTALL_MONITOR" -eq 1 ]]; then
    # Ensure vps_ops venv exists for monitor
    if [[ ! -x "$VPS_OPS_DIR/venv/bin/python" ]]; then
      python3 -m venv "$VPS_OPS_DIR/venv"
      "$VPS_OPS_DIR/venv/bin/pip" install -q --upgrade pip
      "$VPS_OPS_DIR/venv/bin/pip" install -q python-dotenv python-telegram-bot requests
    fi
    $SUDO systemctl enable vps-monitor-batman.service
    $SUDO systemctl restart vps-monitor-batman.service
  fi
fi

echo "=== status ==="
systemctl is-enabled batman-phase1.target 2>/dev/null || true
systemctl is-active batman-drishti.service batman-kavach2.service batman-jagran.service batman-saransh.service 2>/dev/null || true
echo "OK: systemd units installed under /etc/systemd/system/"
