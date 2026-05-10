#!/usr/bin/env bash
# Acuity — on-Pi setup script.
#
# Run this ONCE on a Raspberry Pi running stock Pi OS Lite (64-bit
# Bookworm). After it finishes, the Pi reboots into either:
#   * STA mode joining the team WiFi (if acuity.conf has SSID set)
#   * AP mode "Acuity-Setup-XXXX" exposing a captive portal on port 80
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
#          hostname: acuity
#          enable SSH (with your laptop's pubkey or a password)
#          configure WiFi for your home/laptop network — temporary,
#          we'll wipe this out at the end.
#   2. Boot the Pi, wait 30 s, SSH in.
#   3. Run:
#          curl -fsSL https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/acuity/firmware/install.sh | sudo bash
#      (or clone the repo and run `sudo bash acuity/firmware/install.sh`)
#   4. After it reboots, see acuity/docs/ for what to do next
#      (ship the SD card, clone it, edit acuity.conf, etc.).
#
# === What it does ===
#   * apt-installs the runtime deps (hostapd, dnsmasq, opencv, etc.)
#   * Clones / updates the Acuity repo to /opt/acuity
#   * Builds a Python venv with all wheels (fastapi, pyapriltags, opencv)
#   * Installs systemd units (firstboot + dashboard + setup-wizard)
#   * Drops acuity.conf.example + README-ACUITY.txt into the boot
#     partition so a team can pre-configure their WiFi by editing
#     a text file from any laptop
#   * Enables avahi so the Pi resolves as `acuity-NNNN.local`
#
# Idempotent — re-running upgrades the install in place. Safe to run
# again after a `git pull` from a checked-out copy of the repo.

set -euo pipefail

# === Config ===
REPO_URL="${ACUITY_REPO:-https://github.com/ethancroissants/frc-robotcode.git}"
REPO_BRANCH="${ACUITY_BRANCH:-master}"
INSTALL_DIR="${ACUITY_INSTALL_DIR:-/opt/acuity}"
APP_USER="${ACUITY_USER:-acuity}"

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

    2. If you've already installed Acuity before and just
       want to flip into AP-mode to talk to the Pi:
           sudo /usr/local/bin/acuity-wifi-mode.sh ap

    3. Concurrent STA + AP (advanced): join an internet WiFi while
       keeping the captive-portal AP up so your laptop / phone can
       still reach the Pi at 192.168.50.1 throughout:
           sudo /usr/local/bin/acuity-wifi-mode.sh sta+ap \\
                "YourHomeWiFi" "password"
       Then re-run install.sh on the Pi.

EOF
)"
fi

# === Locate the source files ===
# Two modes:
#   A. Curl-pipe-bash: $0 is a temp file from the pipe and the rest of
#      the repo isn't local. Clone the repo to a scratch dir.
#   B. Run from a checked-out repo: this script lives at
#      <repo>/acuity/firmware/install.sh — use the sibling tree.
#
# After locating ourselves we expose two paths:
#   FIRMWARE_DIR  = .../acuity/firmware   (this script's directory)
#   ACUITY_DIR    = .../acuity            (parent — has dashboard/, libraries/)
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]:-$0}" 2>/dev/null || true)"
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ] \
   && [ -d "$(dirname "$SCRIPT_PATH")/files" ]; then
  FIRMWARE_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
  ACUITY_DIR="$(cd "$FIRMWARE_DIR/.." && pwd)"
  log "running from local checkout at $ACUITY_DIR"
else
  log "no local checkout — cloning $REPO_URL ($REPO_BRANCH) to scratch"
  apt-get update -qq && apt-get install -y -qq git ca-certificates >/dev/null
  CLONE_DIR="$(mktemp -d /tmp/acuity-install.XXXXXX)"
  git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$CLONE_DIR"
  FIRMWARE_DIR="$CLONE_DIR/acuity/firmware"
  ACUITY_DIR="$CLONE_DIR/acuity"
fi
# Back-compat aliases for code below that still uses the old names.
PI_IMAGE_DIR="$FIRMWARE_DIR"
REPO_DIR="$ACUITY_DIR"
[ -d "$FIRMWARE_DIR/files" ]   || fail "missing $FIRMWARE_DIR/files — repo layout changed?"
[ -d "$ACUITY_DIR/dashboard" ] || fail "missing $ACUITY_DIR/dashboard — repo layout changed?"

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
  openssh-server \
  rsync ca-certificates curl git

# Make sure SSH is on. Pi OS Lite ships with sshd installed but
# disabled until either a `/boot/firmware/ssh` flag file or
# Imager-set credentials enable it. Production cards skip both,
# so they boot up unreachable. manufacturer-setup.sh also nukes
# /etc/ssh/ssh_host_* — sshd refuses to start without host keys,
# so we regenerate any missing ones here too. (sshd's own
# generator runs first-boot but only if its own service is up;
# explicit is safer.)
if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
  log "regenerating SSH host keys"
  ssh-keygen -A
fi

# Clean up the older ExecStartPre drop-in approach — it didn't fire
# on Pi OS Bookworm installs that use socket-activated sshd
# (`ssh.socket` → `[email protected]`), which is why customers were
# getting locked out after manufacturer-setup. The oneshot
# `acuity-ssh-keygen.service` (installed below alongside the other
# unit files) runs Before= every SSH-related unit so it covers
# both ssh.service AND ssh.socket variants.
rm -f /etc/systemd/system/ssh.service.d/acuity-keygen.conf \
      /etc/systemd/system/ssh.service.d/cfsight-keygen.conf \
      /etc/systemd/system/sshd.service.d/acuity-keygen.conf \
      /etc/systemd/system/sshd.service.d/cfsight-keygen.conf
rmdir /etc/systemd/system/ssh.service.d  2>/dev/null || true
rmdir /etc/systemd/system/sshd.service.d 2>/dev/null || true

# Enable EVERY SSH unit name we might have. On stock Pi OS Bookworm,
# either `ssh.service` or `ssh.socket` may be the active path
# depending on Imager-flag presence and Pi-OS minor version. Enabling
# both is harmless — systemd treats whichever is masked or absent as
# a no-op. Same for sshd.* (some Debian variants use that name).
for unit in ssh.service ssh.socket sshd.service sshd.socket; do
  systemctl enable "$unit" 2>/dev/null || true
done
# Start whichever exists right now so the local Pi gets SSH back
# without a reboot. Boot-time enablement is what matters for clones.
systemctl start ssh.socket 2>/dev/null \
  || systemctl start ssh.service  2>/dev/null \
  || systemctl start sshd.service 2>/dev/null \
  || true

# Mask the upstream hostapd / dnsmasq services — we run our own
# instances bound to the AP profile only, started/stopped by
# acuity-wifi-mode.sh. NetworkManager handles wlan0 STA mode.
systemctl mask hostapd.service  2>/dev/null || true
systemctl mask dnsmasq.service  2>/dev/null || true

# Unblock WiFi country code so wlan0 isn't soft-blocked.
raspi-config nonint do_wifi_country US 2>/dev/null || true

# === User account ===
# Create the acuity unix user if missing (lives in /opt/acuity,
# member of `video` group so it can talk to /dev/video*). Idempotent.
if ! id "$APP_USER" >/dev/null 2>&1; then
  log "creating user '$APP_USER'"
  useradd --system --create-home --home-dir "/home/$APP_USER" \
          --shell /usr/sbin/nologin --comment "Acuity" \
          "$APP_USER"
fi
usermod -a -G video "$APP_USER"

# === Sync app code into /opt/acuity ===
log "syncing app code to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude=".git" --exclude="__pycache__" --exclude="*.pyc" \
  --exclude="vendor/wheels" --exclude=".venv" \
  "$ACUITY_DIR/dashboard/" "$INSTALL_DIR/sight/"
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

# Defensive: `install -m 644 src dest/` follows symlinks at dest. If a
# previous run, an interrupted manufacturer-setup, or a stray
# `systemctl mask` left any of these as `→ /dev/null` symlinks (which
# is what `systemctl mask` creates for units), `install` would happily
# write the new bytes through the symlink into /dev/null and leave us
# with a 0-byte file or a still-masked unit. We saw exactly this in
# the field — wifi-mode.sh on disk was zero bytes, firstboot.service
# was masked, and `install.sh` had reported success. Unconditionally
# remove the destination first so `install` always lands a real
# regular file.
cp_unit() {
  local src="$1" dest="/etc/systemd/system/$(basename "$1")"
  rm -f "$dest"
  install -m 644 "$src" "$dest"
}
cp_bin() {
  local src="$1" dest="/usr/local/bin/$(basename "$1")"
  rm -f "$dest"
  install -m 755 "$src" "$dest"
}
cp_etc() {
  local src="$1" dest="/etc/acuity/$(basename "$1")"
  rm -f "$dest"
  install -m 644 "$src" "$dest"
}

# In case any of the systemd units are masked (symlink → /dev/null),
# unmask first so `systemctl enable` later in the script can actually
# wire them up.
systemctl unmask acuity-firstboot.service     2>/dev/null || true
systemctl unmask acuity-setup-wizard.service  2>/dev/null || true
systemctl unmask acuity-dashboard.service     2>/dev/null || true

cp_unit "$PI_IMAGE_DIR/files/etc/systemd/system/acuity-firstboot.service"
cp_unit "$PI_IMAGE_DIR/files/etc/systemd/system/acuity-setup-wizard.service"
cp_unit "$PI_IMAGE_DIR/files/etc/systemd/system/acuity-dashboard.service"
cp_unit "$PI_IMAGE_DIR/files/etc/systemd/system/acuity-ssh-keygen.service"

cp_bin "$PI_IMAGE_DIR/files/usr/local/bin/acuity-firstboot.sh"
cp_bin "$PI_IMAGE_DIR/files/usr/local/bin/acuity-wifi-mode.sh"

install -d -m 755 /etc/acuity
cp_etc "$PI_IMAGE_DIR/files/etc/acuity/hostapd-acuity.conf.template"
cp_etc "$PI_IMAGE_DIR/files/etc/acuity/dnsmasq-acuity.conf.template"

# Verify the files actually landed with content. If `install` wrote
# zero bytes (which is the symptom we just defended against), fail
# loudly here instead of letting the Pi reboot into a broken state.
for f in /etc/systemd/system/acuity-firstboot.service \
         /etc/systemd/system/acuity-setup-wizard.service \
         /etc/systemd/system/acuity-dashboard.service \
         /etc/systemd/system/acuity-ssh-keygen.service \
         /usr/local/bin/acuity-firstboot.sh \
         /usr/local/bin/acuity-wifi-mode.sh; do
  [ -s "$f" ] || fail "post-install verification: $f is empty (symlink-to-/dev/null bug?)"
done

# === Boot-partition files ===
# /boot/firmware/ on Pi OS Lite is a FAT32 partition that mounts on a
# laptop when the SD card is plugged in. Files dropped here can be
# edited by anyone — that's how teams pre-configure their WiFi
# without needing the AP wizard at all.
install -d -m 755 /boot/firmware
install -m 644 "$PI_IMAGE_DIR/files/boot/acuity.conf.example"  /boot/firmware/
install -m 644 "$PI_IMAGE_DIR/files/boot/README-ACUITY.txt"    /boot/firmware/

# Migrate legacy cfsight.conf → acuity.conf if present (covers Pis that
# were installed before the rename). Don't clobber an existing
# acuity.conf if one's already there.
if [ -f /boot/firmware/cfsight.conf ] && [ ! -f /boot/firmware/acuity.conf ]; then
  log "migrating /boot/firmware/cfsight.conf → acuity.conf"
  cp /boot/firmware/cfsight.conf /boot/firmware/acuity.conf
fi

# === Disable legacy cfsight units (pre-Acuity-rename installs) ===
# Older versions of this script installed services and scripts under
# `cfsight-*` / cold-fusion-sight names. If we're upgrading in place,
# those leftovers will conflict with the new units (two firstboot
# services trying to drive wlan0, two dashboards trying to bind :8080).
# Disable + remove them. systemctl is forgiving about missing units.
for legacy in cfsight-firstboot.service \
              cfsight-setup-wizard.service \
              cold-fusion-sight.service; do
  systemctl disable --now "$legacy" 2>/dev/null || true
  rm -f "/etc/systemd/system/$legacy" \
        "/etc/systemd/system/multi-user.target.wants/$legacy"
done
# And the per-script binaries.
rm -f /usr/local/bin/cfsight-firstboot.sh \
      /usr/local/bin/cfsight-wifi-mode.sh

# === sudoers drop-in for the dashboard service ===
# The dashboard exposes "Reboot" and "Forget WiFi" buttons that need
# root. Rather than running the dashboard as root, give the `acuity`
# user passwordless sudo for *only* those two narrow commands. The
# /etc/sudoers.d/ file is parsed every time `sudo` runs, so `visudo`
# linting it on install catches typos before we lock anyone out.
log "installing sudoers drop-in for acuity user"
cat > /etc/sudoers.d/acuity-dashboard <<'EOF'
# Acuity dashboard control hooks. Tightly scoped — anything else still
# requires the password.
acuity ALL=(root) NOPASSWD: /sbin/reboot
acuity ALL=(root) NOPASSWD: /usr/sbin/reboot
acuity ALL=(root) NOPASSWD: /bin/systemctl reboot
acuity ALL=(root) NOPASSWD: /bin/rm -f /boot/firmware/acuity.conf
acuity ALL=(root) NOPASSWD: /usr/bin/journalctl
EOF
chmod 0440 /etc/sudoers.d/acuity-dashboard
# Lint, abort the install if it's broken (otherwise we'd ship a card
# that locks every dashboard control).
if ! visudo -c -q -f /etc/sudoers.d/acuity-dashboard; then
  fail "sudoers drop-in failed validation — refusing to ship"
fi

# === avahi mDNS service advertisement ===
# Publishes `_acuity._tcp.local` on the team WiFi so the laptop-side
# Manager app can auto-discover devices without the user typing IPs.
# Port 8080 is the dashboard; the TXT record carries the firmware
# version for the Manager's tile UI.
install -d -m 755 /etc/avahi/services
cat > /etc/avahi/services/acuity.service <<'EOF'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">%h</name>
  <service>
    <type>_acuity._tcp</type>
    <port>8080</port>
    <txt-record>version=0.1.0</txt-record>
    <txt-record>kind=vision-coprocessor</txt-record>
  </service>
</service-group>
EOF

# === Enable services ===
systemctl daemon-reload
systemctl enable acuity-firstboot.service
systemctl enable acuity-dashboard.service
systemctl enable acuity-ssh-keygen.service
systemctl enable avahi-daemon.service
systemctl restart avahi-daemon.service 2>/dev/null || true
# acuity-setup-wizard intentionally NOT enabled at boot — only
# acuity-wifi-mode.sh starts it when entering AP mode.

log "install complete."
log ""
log "Next steps:"
log "  1. (Optional) Drop an acuity.conf onto /boot/firmware/ to"
log "     pre-configure the team WiFi. Without it, the Pi enters"
log "     AP-mode setup on next boot."
log "  2. Reboot:  sudo reboot"
log "  3. After reboot:"
log "       - if acuity.conf was set:   http://acuity-NNNN.local:8080/"
log "       - otherwise: connect to the open AP Acuity-Setup-XXXX"
log "                    from your phone, follow the captive portal."
log ""
log "Mass production: shut down, dd the SD card to fresh cards, ship."
log "  sudo shutdown -h now"
log "  (then on your laptop)"
log "  sudo dd if=/dev/sdX of=acuity-master.img bs=4M status=progress"
log "  sudo dd if=acuity-master.img of=/dev/sdY bs=4M status=progress"
