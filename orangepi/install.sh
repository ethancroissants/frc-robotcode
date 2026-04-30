#!/usr/bin/env bash
# Cold Fusion Sight — Pi-side installer.
#
# Run on the Orange Pi after the host laptop has rsync'd this folder over.
# Idempotent: re-running upgrades/refreshes the install in place.
#
#   curl -fsSL https://example/install.sh | bash         # not how this is run
#   bash install.sh                                       # how this is run
#
# The host script (setup_orangepi.py on the laptop) drives everything; this
# file is what actually executes on the Pi.

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(id -un)"
SERVICE_NAME="cold-fusion-sight"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

log() { printf "\033[36m[install]\033[0m %s\n" "$*"; }
fail() { printf "\033[31m[fail]\033[0m %s\n" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] && fail "Run as the regular user (not root); the script will sudo where needed."

log "install dir: $INSTALL_DIR"
log "user:        $USER_NAME"

# --- 1. apt deps -----------------------------------------------------------
# ffmpeg: hardware MJPEG passthrough from /dev/video0.
# python3-venv: required to create the project venv.
# v4l-utils: useful for `v4l2-ctl --list-devices` debugging.
log "installing apt packages"
sudo apt-get update -y
sudo apt-get install -y ffmpeg python3-venv python3-pip v4l-utils

# --- 2. python venv --------------------------------------------------------
log "creating venv"
if [ ! -d "$INSTALL_DIR/.venv" ]; then
  python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip wheel
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# --- 3. environment file (TEAM/etc) ---------------------------------------
# Touch the env file if missing so systemd doesn't error on EnvironmentFile=.
# Real values get written by `sight-config` (or by setup_orangepi.py). The
# leading `-` in the unit file makes the file optional, but creating it makes
# `sudo sight-config edit` Just Work.
if [ ! -f "$INSTALL_DIR/sight.env" ]; then
  log "writing default sight.env (team 1279)"
  cat > "$INSTALL_DIR/sight.env" <<EOF
TEAM=1279
CAMERA_DEVICE=/dev/video0
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=30
HTTP_PORT=8080
EOF
fi

# --- 4. systemd unit -------------------------------------------------------
log "installing systemd unit"
TMP=$(mktemp)
sed \
  -e "s|__USER__|$USER_NAME|g" \
  -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
  "$INSTALL_DIR/cold-fusion-sight.service" > "$TMP"
sudo install -m 0644 "$TMP" "$SERVICE_FILE"
rm -f "$TMP"

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

log "service status:"
systemctl --no-pager status "$SERVICE_NAME" | sed -n "1,10p" || true

log "done. UI: http://$(hostname -I | awk '{print $1}'):8080/"
