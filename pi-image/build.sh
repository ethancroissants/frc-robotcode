#!/usr/bin/env bash
# Cold Fusion Sight — Pi image builder.
#
# Produces a flashable .img.xz that boots into either:
#   * STA mode joining the team WiFi (if /boot/firmware/cfsight.conf is set)
#   * AP mode "CFSight-Setup-NNNN" exposing a captive portal on port 80
#     where the operator types in their team SSID + password
#
# Wraps pi-gen (the official Raspberry Pi OS image builder) so we get
# all the boring stuff (boot partition, kernel, raspi-config quirks)
# for free, and just bolt on a custom stage that installs our service.
#
# Requirements (Linux host):
#   sudo, git, qemu-user-static, debootstrap, parted, kpartx, xz-utils
#   On Debian/Ubuntu:
#     sudo apt install -y git qemu-user-static debootstrap parted kpartx xz-utils
#
# Usage:
#   ./pi-image/build.sh                # default: arm64 lite, version from VERSION file
#   VERSION=1.2.3 ./pi-image/build.sh  # override version tag
#   KEEP_WORK=1 ./pi-image/build.sh    # don't nuke pi-gen work dir on success
#
# Output: pi-image/out/cfsight-<version>-arm64.img.xz

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORK_DIR="${WORK_DIR:-$SCRIPT_DIR/work}"
OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/out}"
PI_GEN_DIR="$WORK_DIR/pi-gen"
VERSION="${VERSION:-$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo 0.1.0)}"

log()  { printf '\033[36m[build]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

# Sudo check up front so we don't run for 30 minutes and fail at sudo password.
if [ "$EUID" -ne 0 ] && ! sudo -n true 2>/dev/null; then
  log "this script will need sudo for losetup / chroot — caching credentials now"
  sudo -v || fail "sudo required"
fi

# Auto-install host deps if they're missing. Since we use pi-gen's
# Docker path, the only host deps we need are *our wrapper's* tools:
# git for cloning pi-gen, rsync for staging our app source into
# pi-gen's stage, and xz-utils for inspecting the output. Pi-gen's
# heavy chroot deps (quilt, qemu-user-binfmt, etc.) live inside the
# Docker image — no need to install them on the host.
#
# Skip when CI sets CFSIGHT_SKIP_DEPS=1.
if [ "${CFSIGHT_SKIP_DEPS:-0}" != "1" ]; then
  MISSING=()
  for cmd_pkg in \
      "git:git" \
      "rsync:rsync" \
      "xz:xz-utils" \
      "docker:docker.io"; do
    cmd="${cmd_pkg%%:*}"
    pkg="${cmd_pkg##*:}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
      MISSING+=( "$pkg" )
    fi
  done
  if [ "${#MISSING[@]}" -gt 0 ]; then
    log "missing host deps: ${MISSING[*]} — installing via apt-get"
    if ! command -v apt-get >/dev/null 2>&1; then
      fail "host deps missing and this isn't a Debian/Ubuntu system. Install ${MISSING[*]} manually then re-run."
    fi
    sudo apt-get update
    sudo apt-get install -y "${MISSING[@]}"
  fi
fi

mkdir -p "$WORK_DIR" "$OUT_DIR"

# Pin pi-gen to a known-good ref. Master moves fast and breaks builds
# (e.g. they renamed stages, shuffled binfmt expectations, etc.). A
# tagged release is much more stable. The `arm64` branch is the one
# Raspberry Pi maintains for 64-bit builds.
PI_GEN_REF="${PI_GEN_REF:-arm64}"
if [ ! -d "$PI_GEN_DIR" ]; then
  log "cloning pi-gen ref=$PI_GEN_REF"
  git clone --depth 1 -b "$PI_GEN_REF" https://github.com/RPi-Distro/pi-gen.git "$PI_GEN_DIR"
else
  log "reusing existing pi-gen at $PI_GEN_DIR (rm -rf to force re-clone)"
fi

# === pi-gen config ===
# RELEASE=bookworm: latest stable Pi OS (64-bit kernel + userland — required
#   for our pyapriltags / opencv aarch64 wheels).
# Skip stages 3-5 so we get the *Lite* image (no desktop). FAST and small.
# IMG_NAME drives the output filename.
cat > "$PI_GEN_DIR/config" <<EOF
IMG_NAME="cfsight-${VERSION}"
RELEASE="bookworm"
DEPLOY_COMPRESSION="xz"
COMPRESSION_LEVEL="6"
LOCALE_DEFAULT="en_US.UTF-8"
TARGET_HOSTNAME="cfsight"
KEYBOARD_KEYMAP="us"
KEYBOARD_LAYOUT="English (US)"
TIMEZONE_DEFAULT="America/New_York"
FIRST_USER_NAME="cfsight"
FIRST_USER_PASS="cfsight"
DISABLE_FIRST_BOOT_USER_RENAME="1"
ENABLE_SSH="1"
WPA_COUNTRY="US"
PI_GEN_RELEASE="Cold Fusion Sight ${VERSION}"
EOF

# Skip the desktop stages — Lite only.
for s in stage3 stage4 stage5; do
  touch "$PI_GEN_DIR/${s}/SKIP" "$PI_GEN_DIR/${s}/SKIP_IMAGES"
done

# === stage-cfsight: our customizations ===
log "staging stage-cfsight"
rm -rf "$PI_GEN_DIR/stage-cfsight"
cp -r "$SCRIPT_DIR/stage-cfsight" "$PI_GEN_DIR/stage-cfsight"

# Bring our app source + setup-wizard into the stage so 01-run.sh can
# rsync them into the chroot rootfs. We copy here (not symlink) so a
# rebuild reflects the latest commit's content even if you nuked the
# stage directory by hand.
#
# We *don't* rsync any "firstboot" tree — early scaffolding had a
# pi-image/firstboot/ directory but the firstboot scripts (.service,
# .sh) actually live in stage-cfsight/00-cfsight/files/ and ride along
# with the stage automatically. No separate copy needed.
log "copying app source into stage-cfsight"
mkdir -p "$PI_GEN_DIR/stage-cfsight/00-cfsight/cfsight-source"
rsync -a --delete \
  --exclude=".git" --exclude="__pycache__" --exclude="*.pyc" \
  --exclude="vendor/wheels" --exclude=".venv" \
  "$PROJECT_ROOT/orangepi/" \
  "$PI_GEN_DIR/stage-cfsight/00-cfsight/cfsight-source/sight/"
rsync -a --delete \
  --exclude=".git" --exclude="__pycache__" \
  "$SCRIPT_DIR/setup-wizard/" \
  "$PI_GEN_DIR/stage-cfsight/00-cfsight/cfsight-source/setup-wizard/"

# === Register qemu binfmts on the host kernel ===
# Even though pi-gen runs inside Docker, the kernel needs to know how
# to execute foreign-arch (aarch64) binaries inside the chroot — this
# is binfmt_misc registration, which is a host-kernel concern shared
# between containers and the host. On older Linux this was handled by
# the qemu-user-binfmt apt package, but Ubuntu 24.04 made it conflict
# with qemu-user-static so neither approach is universal anymore. The
# multiarch/qemu-user-static container registers handlers via
# --privileged + the kernel's binfmt_misc interface and works on
# every modern Linux host.
log "registering qemu binfmts via multiarch/qemu-user-static"
sudo docker run --rm --privileged multiarch/qemu-user-static:latest \
    --reset -p yes >/dev/null \
    || fail "binfmt registration failed — check kernel binfmt_misc support"

# === Build ===
# We use pi-gen's *Docker* path (./build-docker.sh) instead of the
# host path (./build.sh). Reasons:
#   1. Pi-gen pins specific dep versions inside its Docker image, so
#      host distro / version drift doesn't bite us.
#   2. The image is cached after first run, so re-builds are faster.
#   3. CI runners have Docker pre-installed; no extra setup.
log "building image via pi-gen's Docker path (this takes ~15-30 min)"
cd "$PI_GEN_DIR"
if ! command -v docker >/dev/null 2>&1; then
  fail "docker not installed — install docker.io / docker-ce, or run on a host with Docker"
fi
sudo CONTINUE=1 ./build-docker.sh 2>&1 | sed 's/^/  /'

# === Collect ===
# Pi-gen sometimes deposits artifacts under deploy/ AND sometimes under
# work/<imgname>/<stage>/exports/ depending on version. Walk both so
# we don't fail purely because of layout drift between pi-gen tags.
DEPLOY_DIRS=( "$PI_GEN_DIR/deploy" "$PI_GEN_DIR/work" )
log "collecting build output"
shopt -s nullglob
moved=0
for d in "${DEPLOY_DIRS[@]}"; do
  [ -d "$d" ] || continue
  while IFS= read -r f; do
    cp -v "$f" "$OUT_DIR/"
    moved=$((moved + 1))
  done < <(find "$d" -maxdepth 5 -type f \( -name '*.img.xz' -o -name '*.img' -o -name '*.zip' \) 2>/dev/null)
done
shopt -u nullglob
if [ "$moved" -eq 0 ]; then
  log "no image found! pi-gen layout for debugging:"
  find "$PI_GEN_DIR/deploy" "$PI_GEN_DIR/work" -maxdepth 4 -type f 2>/dev/null | head -50 || true
  fail "no .img.xz / .img / .zip produced. See log above for what pi-gen did write."
fi

if [ "${KEEP_WORK:-0}" != "1" ]; then
  log "cleaning pi-gen work dir (set KEEP_WORK=1 to skip)"
  sudo rm -rf "$PI_GEN_DIR/work"
fi

log "done. flash with Raspberry Pi Imager → 'Use custom image' → $OUT_DIR/cfsight-${VERSION}-arm64.img.xz"
log "after flashing, edit the boot partition's cfsight.conf to pre-set team WiFi,"
log "or just power on and look for the open AP 'CFSight-Setup-XXXX'."
