#!/bin/bash -e
# 01-run.sh runs OUTSIDE the chroot but with $ROOTFS_DIR pointing at the
# image's root filesystem. We use it to copy our app source files in,
# then use on_chroot to finish per-OS setup (systemd unit installs,
# venv creation, etc.).
#
# The cfsight-source/ directory next to this file is populated by
# pi-image/build.sh from the project's orangepi/ + setup-wizard/ trees.
# (The firstboot scripts live alongside this file in files/ — they
# don't need a separate copy step.)

STAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$STAGE_DIR/cfsight-source"

if [ ! -d "$SRC" ]; then
  echo "ERROR: $SRC not found — pi-image/build.sh should have populated it" >&2
  exit 1
fi

# === Copy app code into image ===
install -d -m 755 "$ROOTFS_DIR/opt/cfsight"
rsync -a --delete \
  --chown=root:root \
  "$SRC/sight/"          "$ROOTFS_DIR/opt/cfsight/sight/"
rsync -a --delete \
  --chown=root:root \
  "$SRC/setup-wizard/"   "$ROOTFS_DIR/opt/cfsight/setup-wizard/"

# === Drop a default config skeleton onto the boot partition ===
# /boot/firmware/ is FAT32 — accessible from a host (Windows/macOS) when
# the SD card is plugged in. So a team can pre-configure their WiFi
# without running the AP wizard at all: edit cfsight.conf in a text
# editor before booting.
install -d -m 755 "$ROOTFS_DIR/boot/firmware"
install -m 644 "$STAGE_DIR/files/cfsight.conf.example" \
  "$ROOTFS_DIR/boot/firmware/cfsight.conf.example"
install -m 644 "$STAGE_DIR/files/README-CFSIGHT.txt" \
  "$ROOTFS_DIR/boot/firmware/README-CFSIGHT.txt"

# === systemd units + helper scripts ===
install -m 644 "$STAGE_DIR/files/cfsight-firstboot.service" \
  "$ROOTFS_DIR/etc/systemd/system/cfsight-firstboot.service"
install -m 644 "$STAGE_DIR/files/cfsight-setup-wizard.service" \
  "$ROOTFS_DIR/etc/systemd/system/cfsight-setup-wizard.service"
install -m 644 "$STAGE_DIR/files/cold-fusion-sight.service" \
  "$ROOTFS_DIR/etc/systemd/system/cold-fusion-sight.service"

install -m 755 "$STAGE_DIR/files/cfsight-firstboot.sh" \
  "$ROOTFS_DIR/usr/local/bin/cfsight-firstboot.sh"
install -m 755 "$STAGE_DIR/files/cfsight-wifi-mode.sh" \
  "$ROOTFS_DIR/usr/local/bin/cfsight-wifi-mode.sh"

# AP-mode infrastructure config templates (rendered by cfsight-firstboot.sh
# when AP mode is needed).
install -d -m 755 "$ROOTFS_DIR/etc/cfsight"
install -m 644 "$STAGE_DIR/files/hostapd-cfsight.conf.template" \
  "$ROOTFS_DIR/etc/cfsight/hostapd-cfsight.conf.template"
install -m 644 "$STAGE_DIR/files/dnsmasq-cfsight.conf.template" \
  "$ROOTFS_DIR/etc/cfsight/dnsmasq-cfsight.conf.template"

# === In-chroot finalisation ===
on_chroot <<'CHROOT'
set -e

# Disable the upstream hostapd / dnsmasq services — we run our own
# instances bound to the AP profile only, started/stopped by
# cfsight-wifi-mode.sh. NetworkManager handles wlan0 STA mode.
systemctl mask hostapd.service        2>/dev/null || true
systemctl mask dnsmasq.service        2>/dev/null || true

# rfkill: ensure WiFi is unblocked at boot. Pi OS ships with WiFi soft-
# blocked until WPA country is set; we set it via raspi-config below.
raspi-config nonint do_wifi_country US || true

# Enable our services. cfsight-firstboot runs once per boot and decides
# AP-or-STA before the dashboard service starts. setup-wizard is only
# started by cfsight-wifi-mode.sh when we enter AP mode.
systemctl enable cfsight-firstboot.service
systemctl enable cold-fusion-sight.service

# === Python venv + deps ===
# We do this in the chroot so the image ships with a working venv and
# all wheels — first boot has no internet anyway.
INSTALL_DIR=/opt/cfsight
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip wheel
# Sight + setup-wizard share the same venv — both are FastAPI apps and
# their deps overlap heavily. The combined requirements file lives at
# /opt/cfsight/requirements.txt.
cp "$INSTALL_DIR/sight/requirements.txt" "$INSTALL_DIR/requirements.txt"
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Permissions: the cfsight unix user should own its tree so it doesn't
# need root to write recordings / soundboard / etc. (We created the
# user via FIRST_USER_NAME in pi-gen config.)
chown -R cfsight:cfsight /opt/cfsight

# === avahi (mDNS): cfsight-NNNN.local works on every modern client ===
# The hostname is set per-boot by cfsight-firstboot.sh based on team
# number from cfsight.conf. avahi auto-publishes the current hostname
# so cfsight-1279.local just works without any avahi-tool config.
systemctl enable avahi-daemon
CHROOT
