#!/usr/bin/env bash
# Cold Fusion Sight — Pi-side installer.
#
# Run on the Orange Pi after the host laptop has rsync'd this folder over.
# Idempotent: re-running upgrades/refreshes the install in place.
#
# Driven by setup_orangepi.py on the laptop. Reads two optional env vars:
#   TEAM=1279         # FRC team — used to pin the static IP at 10.TE.AM.11
#   STATIC_IFACE=eth0 # which interface to pin (default eth0)

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(id -un)"
SERVICE_NAME="cold-fusion-sight"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

TEAM="${TEAM:-1279}"
STATIC_IFACE="${STATIC_IFACE:-eth0}"

log() { printf "\033[36m[install]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[warn]\033[0m %s\n" "$*"; }
fail() { printf "\033[31m[fail]\033[0m %s\n" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] && fail "Run as the regular user (not root); the script will sudo where needed."

log "install dir: $INSTALL_DIR"
log "user:        $USER_NAME"
log "team:        $TEAM"

# Compute the Pi's static IP from the team number, FRC convention:
#   radio = 10.TE.AM.1
#   rio   = 10.TE.AM.2
#   Pi    = 10.TE.AM.11    (first coprocessor slot)
TE=$((TEAM / 100))
AM=$((TEAM % 100))
PI_IP="10.${TE}.${AM}.11"
GATEWAY="10.${TE}.${AM}.1"
NETMASK_BITS=24

# --- 1. apt deps -----------------------------------------------------------
# The Pi normally lives on the FRC robot network with no internet. The
# laptop-side setup (setup_orangepi.py) probes which apt packages are
# already installed and passes the missing ones via $APT_MISSING. If
# nothing's missing we skip apt entirely (the common case on a Pi OS Full
# image, which already has libgl1/libglib2/v4l-utils/python3-venv).
#
# python deps: venv + pip
# camera deps: ffmpeg (legacy passthrough fallback) + v4l-utils (debugging)
# opencv deps: libgl1 + libglib2.0-0(t64) are pulled in by opencv-python at
#   import time, even on the -headless variant — without them you get
#   "ImportError: libGL.so.1: cannot open shared object file" the first
#   time the service tries to import cv2.
APT_MISSING="${APT_MISSING:-}"
if [ -n "$APT_MISSING" ]; then
  log "apt packages still missing: $APT_MISSING"
  # Try the local apt cache only (--no-download). Works iff the Pi was
  # online previously and `apt-get update && apt-get install` had cached
  # these. If not, we print a clear ONE-TIME hotspot recipe.
  if sudo apt-get install -y --no-download $APT_MISSING 2>/dev/null; then
    log "installed from local apt cache"
  else
    fail "
   ===========================================================
   apt packages missing on the Pi:  $APT_MISSING

   The Pi has no internet, and these aren't cached. Run this
   ONCE on the Pi (connect it to a phone hotspot or any WiFi
   with internet for ~2 minutes):

     sudo apt-get update
     sudo apt-get install -y $APT_MISSING

   Then move the Pi back to the robot network and re-run
   Vision Pi setup. From that point on the Pi never needs
   internet again.
   ==========================================================="
  fi
else
  log "all required apt packages already installed — skipping apt step"
fi

# --- 2. python venv --------------------------------------------------------
log "creating venv"
if [ ! -d "$INSTALL_DIR/.venv" ]; then
  python3 -m venv "$INSTALL_DIR/.venv"
fi

# Offline pip install: setup_orangepi.py pre-downloads matching wheels into
# vendor/wheels/ so the Pi never has to talk to PyPI. --no-index forces pip
# to ignore the network entirely; --find-links points it at the local cache.
#
# Idempotency: hash requirements.txt + the venv's python binary path/version
# into .pip-stamp. If the stamp matches, every dep is already installed for
# this exact venv, so we skip the (slow) pip resolve/install on re-runs.
USE_LOCAL_WHEELS="${USE_LOCAL_WHEELS:-0}"
WHEELS_DIR="$INSTALL_DIR/vendor/wheels"
PIP_STAMP="$INSTALL_DIR/.venv/.pip-stamp"
PY_VER="$("$INSTALL_DIR/.venv/bin/python" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
PIP_STAMP_EXPECTED="$(sha256sum "$INSTALL_DIR/requirements.txt" | awk '{print $1}')|py=$PY_VER"

if [ -f "$PIP_STAMP" ] && [ "$(cat "$PIP_STAMP")" = "$PIP_STAMP_EXPECTED" ]; then
  log "pip deps already satisfied (requirements.txt unchanged) — skipping"
elif [ "$USE_LOCAL_WHEELS" = "1" ] && [ -d "$WHEELS_DIR" ] && \
   ls "$WHEELS_DIR"/*.whl >/dev/null 2>&1; then
  log "installing pip deps offline from $WHEELS_DIR"
  "$INSTALL_DIR/.venv/bin/pip" install --no-index --find-links "$WHEELS_DIR" \
    -r "$INSTALL_DIR/requirements.txt"
  echo "$PIP_STAMP_EXPECTED" > "$PIP_STAMP"
else
  log "installing pip deps online (no local wheel cache)"
  "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
  echo "$PIP_STAMP_EXPECTED" > "$PIP_STAMP"
fi

# --- 3. environment file (TEAM/etc) ---------------------------------------
# Touch the env file if missing so systemd doesn't error on EnvironmentFile=.
# Idempotent: if it exists, we update TEAM= but leave camera knobs untouched.
if [ ! -f "$INSTALL_DIR/sight.env" ]; then
  log "writing default sight.env"
  cat > "$INSTALL_DIR/sight.env" <<EOF
TEAM=${TEAM}
CAMERA_DEVICE=/dev/video0
# 640x480 is the universal hardware-MJPEG mode on USB cameras and gives
# the AprilTag detector enough headroom to hit 30 fps end-to-end on the
# Pi 5. Bump to 1280x720 if your camera + lens warrant it.
CAMERA_WIDTH=640
CAMERA_HEIGHT=480
CAMERA_FPS=30
HTTP_PORT=8080

# Comma-separated AprilTag IDs that count as "the goal" by default. The
# operator can override per-shot by clicking a tag in the UI.
TARGET_TAG_IDS=3,4,7,8

# Ready-to-fire bearing band — SHOOT only arms when |bearing| <= this.
READY_BEARING_DEG=2.5
EOF
else
  # Replace TEAM= line so re-running with a new team picks up the change.
  sed -i.bak "/^TEAM=/d" "$INSTALL_DIR/sight.env"
  echo "TEAM=${TEAM}" >> "$INSTALL_DIR/sight.env"
fi

# --- 4. static IP on the robot network ------------------------------------
# FRC robots have a fixed-topology subnet; pinning the Pi keeps everything
# (rio, browser bookmark) reaching it at a known address. We try
# NetworkManager (modern Armbian default) first, then fall back to
# /etc/network/interfaces.d/ which ifupdown respects.
configure_static_ip() {
  # Detect whether we're being run over an SSH session whose source IP
  # would be cut off by switching this interface. If so, we defer the
  # `nmcli connection up` step — bringing the new connection up
  # immediately switches eth0's address out from under the active SSH
  # session, the laptop sees `Connection reset`, and all subsequent
  # install.sh log output is lost. Deferring with systemd-run lets
  # install.sh exit cleanly first.
  CURRENT_IP_ON_IFACE="$(ip -4 -o addr show "$STATIC_IFACE" 2>/dev/null \
    | awk '{print $4}' | cut -d/ -f1 | head -n1)"
  SSH_DEST_IP="$(echo "${SSH_CONNECTION:-}" | awk '{print $3}')"
  DEFER_BOUNCE=0
  if [ -n "$SSH_DEST_IP" ] && [ "$SSH_DEST_IP" = "$CURRENT_IP_ON_IFACE" ] \
     && [ "$CURRENT_IP_ON_IFACE" != "$PI_IP" ]; then
    DEFER_BOUNCE=1
  fi

  if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
    log "pinning $STATIC_IFACE to $PI_IP via NetworkManager"
    # Find or create a connection profile for this interface.
    CONN_NAME="cold-fusion-${STATIC_IFACE}"
    if ! nmcli -t -f NAME connection show | grep -qx "$CONN_NAME"; then
      sudo nmcli connection add type ethernet ifname "$STATIC_IFACE" \
        con-name "$CONN_NAME" >/dev/null
    fi
    sudo nmcli connection modify "$CONN_NAME" \
      ipv4.method manual \
      ipv4.addresses "${PI_IP}/${NETMASK_BITS}" \
      ipv4.gateway "$GATEWAY" \
      ipv4.dns "$GATEWAY 1.1.1.1" \
      connection.autoconnect yes \
      connection.autoconnect-priority 100
    if [ "$DEFER_BOUNCE" = "1" ]; then
      log "deferring connection bounce so this SSH session survives"
      log "  → IP will switch to $PI_IP about 8s after install.sh exits"
      sudo systemd-run --on-active=8s --unit=cf-pin-ip \
        nmcli connection up "$CONN_NAME" >/dev/null 2>&1 || \
        warn "systemd-run unavailable; reboot to apply the static IP."
    else
      sudo nmcli connection up "$CONN_NAME" \
        || warn "couldn't bring up $CONN_NAME yet (cable not in robot network?)"
    fi
    return 0
  fi

  if [ -d /etc/network/interfaces.d ]; then
    log "pinning $STATIC_IFACE to $PI_IP via ifupdown"
    sudo tee "/etc/network/interfaces.d/10-cold-fusion-${STATIC_IFACE}" >/dev/null <<EOF
auto ${STATIC_IFACE}
iface ${STATIC_IFACE} inet static
    address ${PI_IP}
    netmask 255.255.255.0
    gateway ${GATEWAY}
EOF
    if [ "$DEFER_BOUNCE" = "1" ]; then
      log "deferring networking restart so this SSH session survives"
      sudo systemd-run --on-active=8s --unit=cf-pin-ip \
        systemctl restart networking >/dev/null 2>&1 || \
        warn "systemd-run unavailable; reboot to apply the static IP."
    else
      sudo systemctl restart networking || true
    fi
    return 0
  fi

  warn "Couldn't pin static IP — neither NetworkManager nor ifupdown found."
  warn "Run 'sudo nmtui' (or your distro's equivalent) and set $STATIC_IFACE to ${PI_IP}/${NETMASK_BITS}."
  return 1
}
configure_static_ip || true

# --- 5. sudoers rule for rio-driven restart -------------------------------
# When the rio pushes new orangepi/ files it needs to `systemctl restart
# cold-fusion-sight` without a password. We only grant *that one command*,
# not blanket sudo. NOPASSWD only on systemctl restart/status of our service.
log "installing sudoers rule for rio-driven restart"
sudo tee /etc/sudoers.d/cold-fusion-sight >/dev/null <<EOF
# Allow ${USER_NAME} to manage the cold-fusion-sight service without a
# password. Required so the rio (which SSHes here as ${USER_NAME}) can
# restart the service after pushing new code.
${USER_NAME} ALL=(root) NOPASSWD: /bin/systemctl restart cold-fusion-sight, /bin/systemctl status cold-fusion-sight, /usr/bin/systemctl restart cold-fusion-sight, /usr/bin/systemctl status cold-fusion-sight
EOF
sudo chmod 0440 /etc/sudoers.d/cold-fusion-sight

# --- 6. systemd unit -------------------------------------------------------
# Only daemon-reload if the rendered unit file actually differs (cheap
# optimization, avoids unnecessary systemctl chatter). But ALWAYS restart
# the service — the unit file is small and rarely changes, while the
# application code (server.py, static/, etc.) changes every push, and the
# running uvicorn process holds the old code in memory until restart.
# Skipping the restart is what made "I pushed new code but the Pi is
# still serving the old version" happen.
TMP=$(mktemp)
sed \
  -e "s|__USER__|$USER_NAME|g" \
  -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
  "$INSTALL_DIR/cold-fusion-sight.service" > "$TMP"

if [ ! -f "$SERVICE_FILE" ] || ! sudo cmp -s "$TMP" "$SERVICE_FILE"; then
  log "installing systemd unit"
  sudo install -m 0644 "$TMP" "$SERVICE_FILE"
  sudo systemctl daemon-reload
fi
rm -f "$TMP"

sudo systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
log "restarting $SERVICE_NAME (picks up new code)"
sudo systemctl restart "$SERVICE_NAME"

log "service status:"
systemctl --no-pager status "$SERVICE_NAME" | sed -n "1,10p" || true

CURRENT_IP="$(hostname -I | awk '{print $1}')"
log "done."
log "  on robot network → http://${PI_IP}:8080/"
log "  current IP       → http://${CURRENT_IP:-<unknown>}:8080/"
log "  mDNS hostname    → http://orangepi.local:8080/"
