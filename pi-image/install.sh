#!/usr/bin/env bash
# Cold Fusion Sight — on-Pi setup script.
#
# Run this ONCE on a Raspberry Pi running stock Pi OS Lite (64-bit
# Bookworm). After it finishes, the Pi reboots into either:
#   * STA mode joining the team WiFi (if cfsight.conf has SSID set)
#   * AP mode "CFSight-Setup-XXXX" exposing a captive portal on port 80
#
# This replaces the old "build a custom image in CI" flow. Reasons:
#   * pi-gen + cross-arch + Docker + binfmts is a maintenance nightmare;
#     there are 12 ways for it to break and one to succeed.
#   * Running natively on the Pi avoids ALL of those — apt/pip/systemd
#     are doing what they were designed for, on the right architecture.
#   * For mass production, you `dd if=/dev/sdX` an already-installed
#     SD card to a fresh card. Same end result, infinitely simpler.
#
# === Quick start ===
#   1. Flash Pi OS Lite (Bookworm 64-bit) with Raspberry Pi Imager.
#      In Imager's advanced settings, set:
#          hostname: cfsight
#          enable SSH (with your laptop's pubkey or a password)
#          configure WiFi for your home/laptop network — temporary,
#          we'll wipe this out at the end.
#   2. Boot the Pi, wait 30 s, SSH in.
#   3. Run:
#          curl -fsSL https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/pi-image/install.sh | sudo bash
#      (or clone the repo and run `sudo bash pi-image/install.sh`)
#   4. After it reboots, see pi-image/README.md for what to do next
#      (ship the SD card, clone it, edit cfsight.conf, etc.).
#
# === What it does ===
#   * apt-installs the runtime deps (hostapd, dnsmasq, opencv, etc.)
#   * Clones / updates the cfsight repo to /opt/cfsight
#   * Builds a Python venv with all wheels (fastapi, pyapriltags, opencv)
#   * Installs systemd units (firstboot + dashboard + setup-wizard)
#   * Drops cfsight.conf.example + README-CFSIGHT.txt into the boot
#     partition so a team can pre-configure their WiFi by editing
#     a text file from any laptop
#   * Enables avahi so the Pi resolves as `cfsight-NNNN.local`
#
# Idempotent — re-running upgrades the install in place. Safe to run
# again after a `git pull` from a checked-out copy of the repo.

set -euo pipefail

# === Config ===
REPO_URL="${CFSIGHT_REPO:-https://github.com/ethancroissants/frc-robotcode.git}"
REPO_BRANCH="${CFSIGHT_BRANCH:-master}"
INSTALL_DIR="${CFSIGHT_INSTALL_DIR:-/opt/cfsight}"
APP_USER="${CFSIGHT_USER:-cfsight}"

log()  { printf '\033[36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

# === Sanity checks ===
[ "$EUID" -eq 0 ] || fail "run as root (sudo bash install.sh)"

if [ -f /etc/os-release ]; then
  . /etc/os-release
  case "$ID" in
    raspbian|debian|ubuntu) : ;;
    *) warn "untested OS: $ID — proceeding anyway" ;;
  esac
else
  warn "no /etc/os-release; assuming Debian/Pi-OS-compatible"
fi

ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "$ARCH" in
  arm64|aarch64) : ;;
  *) warn "this is built for arm64 (Pi 3/4/5/Zero 2 W); your arch is $ARCH — pyapriltags may not have a wheel" ;;
esac

# Internet check up front — fails fast with a clear message instead
# of letting apt-get / pip die mid-run with cryptic timeouts. This
# is the single most common gotcha when running install.sh on a Pi
# that's currently configured for a no-internet team WiFi.
if ! curl -fsSL --max-time 8 -o /dev/null https://deb.debian.org/ 2>/dev/null \
   && ! curl -fsSL --max-time 8 -o /dev/null https://github.com/ 2>/dev/null; then
  fail "$(cat <<EOF

  No internet detected. install.sh needs to apt-install + pip-install
  ~150 MB of dependencies (OpenCV, FastAPI, pyapriltags, etc.).

  Options:
    1. Move the Pi onto an internet-connected WiFi (your home network,
       a phone hotspot, etc.) and re-run install.sh. After it finishes
       you can move it back to the no-internet network.

    2. If you've already installed Cold Fusion Sight before and just
       want to flip into AP-mode to talk to the Pi:
           sudo /usr/local/bin/cfsight-wifi-mode.sh ap

    3. Concurrent STA + AP (advanced): join an internet WiFi while
       keeping the captive-portal AP up so your laptop / phone can
       still reach the Pi at 192.168.50.1 throughout:
           sudo /usr/local/bin/cfsight-wifi-mode.sh sta+ap \\
                "YourHomeWiFi" "password"
       Then re-run install.sh on the Pi.

EOF
)"
fi

# === Locate the source files ===
# Two modes:
#   A. Curl-pipe-bash: $0 is a temp file from the pipe and the rest of
#      the repo isn't local. Clone it to a scratch dir.
#   B. Run from a checked-out repo: this script lives at
#      <repo>/pi-image/install.sh — use the sibling tree directly.
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]:-$0}" 2>/dev/null || true)"
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ] \
   && [ -d "$(dirname "$SCRIPT_PATH")/files" ]; then
  PI_IMAGE_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
  REPO_DIR="$(cd "$PI_IMAGE_DIR/.." && pwd)"
  log "running from local checkout at $REPO_DIR"
else
  log "no local checkout — cloning $REPO_URL ($REPO_BRANCH) to scratch"
  apt-get update -qq && apt-get install -y -qq git ca-certificates >/dev/null
  REPO_DIR="$(mktemp -d /tmp/cfsight-install.XXXXXX)"
  git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
  PI_IMAGE_DIR="$REPO_DIR/pi-image"
fi
[ -d "$PI_IMAGE_DIR/files" ] || fail "missing $PI_IMAGE_DIR/files — repo layout changed?"
[ -d "$REPO_DIR/orangepi" ]  || fail "missing $REPO_DIR/orangepi — repo layout changed?"

# === Apt deps ===
log "apt-get update + install runtime packages"
apt-get update
# Most of these are runtime deps for the dashboard service or for
# AP-mode setup. python3-venv is needed because pi-os-lite ships
# python3 without the venv module by default.
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv \
  v4l-utils libgl1 libglib2.0-0 \
  hostapd dnsmasq-base \
  iptables iw wireless-tools wpasupplicant \
  network-manager \
  avahi-daemon libnss-mdns \
  rsync ca-certificates curl git

# Mask the upstream hostapd / dnsmasq services — we run our own
# instances bound to the AP profile only, started/stopped by
# cfsight-wifi-mode.sh. NetworkManager handles wlan0 STA mode.
systemctl mask hostapd.service  2>/dev/null || true
systemctl mask dnsmasq.service  2>/dev/null || true

# Unblock WiFi country code so wlan0 isn't soft-blocked.
raspi-config nonint do_wifi_country US 2>/dev/null || true

# === User account ===
# Create the cfsight unix user if missing (lives in /opt/cfsight,
# member of `video` group so it can talk to /dev/video*). Idempotent.
if ! id "$APP_USER" >/dev/null 2>&1; then
  log "creating user '$APP_USER'"
  useradd --system --create-home --home-dir "/home/$APP_USER" \
          --shell /usr/sbin/nologin --comment "Cold Fusion Sight" \
          "$APP_USER"
fi
usermod -a -G video "$APP_USER"

# === Sync app code into /opt/cfsight ===
log "syncing app code to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude=".git" --exclude="__pycache__" --exclude="*.pyc" \
  --exclude="vendor/wheels" --exclude=".venv" \
  "$REPO_DIR/orangepi/" "$INSTALL_DIR/sight/"
rsync -a --delete \
  --exclude=".git" --exclude="__pycache__" \
  "$PI_IMAGE_DIR/setup-wizard/" "$INSTALL_DIR/setup-wizard/"

# Combined requirements.txt — sight + setup-wizard share the same venv.
cp "$INSTALL_DIR/sight/requirements.txt" "$INSTALL_DIR/requirements.txt"

# === Python venv ===
log "creating / updating venv"
if [ ! -d "$INSTALL_DIR/.venv" ]; then
  python3 -m venv "$INSTALL_DIR/.venv"
fi
"$INSTALL_DIR/.venv/bin/pip" install --no-cache-dir --upgrade pip wheel
log "installing python deps (this is the slow part — ~5-10 min on Pi Zero 2 W)"
"$INSTALL_DIR/.venv/bin/pip" install --no-cache-dir -r "$INSTALL_DIR/requirements.txt"

# Smoke-test: bail loudly if a critical dep didn't land.
"$INSTALL_DIR/.venv/bin/python" -c "import fastapi, uvicorn, cv2, pyapriltags" \
  || fail "venv is missing critical deps — see pip output above"

chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"

# === systemd units + helper scripts ===
log "installing systemd units + helper scripts"

install -m 644 "$PI_IMAGE_DIR/files/etc/systemd/system/cfsight-firstboot.service"     /etc/systemd/system/
install -m 644 "$PI_IMAGE_DIR/files/etc/systemd/system/cfsight-setup-wizard.service"  /etc/systemd/system/
install -m 644 "$PI_IMAGE_DIR/files/etc/systemd/system/cold-fusion-sight.service"     /etc/systemd/system/

install -m 755 "$PI_IMAGE_DIR/files/usr/local/bin/cfsight-firstboot.sh"    /usr/local/bin/
install -m 755 "$PI_IMAGE_DIR/files/usr/local/bin/cfsight-wifi-mode.sh"    /usr/local/bin/

install -d -m 755 /etc/cfsight
install -m 644 "$PI_IMAGE_DIR/files/etc/cfsight/hostapd-cfsight.conf.template"   /etc/cfsight/
install -m 644 "$PI_IMAGE_DIR/files/etc/cfsight/dnsmasq-cfsight.conf.template"   /etc/cfsight/

# === Boot-partition files ===
# /boot/firmware/ on Pi OS Lite is a FAT32 partition that mounts on a
# laptop when the SD card is plugged in. Files dropped here can be
# edited by anyone — that's how teams pre-configure their WiFi
# without needing the AP wizard at all.
install -d -m 755 /boot/firmware
install -m 644 "$PI_IMAGE_DIR/files/boot/cfsight.conf.example"  /boot/firmware/
install -m 644 "$PI_IMAGE_DIR/files/boot/README-CFSIGHT.txt"    /boot/firmware/

# === Enable services ===
systemctl daemon-reload
systemctl enable cfsight-firstboot.service
systemctl enable cold-fusion-sight.service
systemctl enable avahi-daemon.service
# cfsight-setup-wizard intentionally NOT enabled at boot — only
# cfsight-wifi-mode.sh starts it when entering AP mode.

log "install complete."
log ""
log "Next steps:"
log "  1. (Optional) Drop a cfsight.conf onto /boot/firmware/ to"
log "     pre-configure the team WiFi. Without it, the Pi enters"
log "     AP-mode setup on next boot."
log "  2. Reboot:  sudo reboot"
log "  3. After reboot:"
log "       - if cfsight.conf was set:   http://cfsight-NNNN.local:8080/"
log "       - otherwise: connect to the open AP CFSight-Setup-XXXX"
log "                    from your phone, follow the captive portal."
log ""
log "Mass production: shut down, dd the SD card to fresh cards, ship."
log "  sudo shutdown -h now"
log "  (then on your laptop)"
log "  sudo dd if=/dev/sdX of=cfsight-master.img bs=4M status=progress"
log "  sudo dd if=cfsight-master.img of=/dev/sdY bs=4M status=progress"
