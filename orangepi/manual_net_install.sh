#!/usr/bin/env bash
# Cold Fusion Sight — manual network install for Pis without WiFi.
#
# When to use this:
#   The laptop-side `setup_orangepi.py` wizard handles everything for Pis
#   with built-in WiFi (Raspberry Pi 5, Orange Pi 5B/5 Plus/5 Pro, etc.) by
#   briefly toggling the Pi's wlan0 onto a network you supply, fetching
#   apt packages + pip wheels, then disconnecting. That doesn't work on
#   Pis that have NO wlan0 — most notably the **base Orange Pi 5 (v1.x)**,
#   which is ethernet-only.
#
#   This script does the same fetch, but runs on the Pi while it's plugged
#   into a network that already has internet (e.g. your home router).
#   Once it finishes, plug the Pi back into the robot network and run
#   "Set up / Update Vision Pi" from the laptop — the wizard will detect
#   the cache stamp and skip the bridge entirely.
#
# Usage (one-liner, from an SSH session on the Pi):
#
#   curl -sSL https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/orangepi/manual_net_install.sh | bash
#
# Or if you cloned the repo locally on the Pi for some reason:
#
#   bash orangepi/manual_net_install.sh
#
# Override knobs (env vars, optional):
#   CFR_REPO_RAW   — base URL for raw.githubusercontent.com lookups.
#   CFR_INSTALL_DIR — where the wheel cache lands (default ~/cold-fusion-sight).

set -euo pipefail

REPO_RAW="${CFR_REPO_RAW:-https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master}"
INSTALL_DIR="${CFR_INSTALL_DIR:-$HOME/cold-fusion-sight}"

log()  { printf '\033[36m[manual-install]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

# Confirm we have internet before we burn the user's time on apt updates.
log "checking internet connectivity"
if ! curl -fsSL --max-time 5 -o /dev/null https://raw.githubusercontent.com/; then
  fail "no internet — plug the Pi into a network that has internet first."
fi

# 1. apt: the same package list setup_orangepi.py probes for. The
#    libglib2.0-0t64 / libglib2.0-0 alternation handles the t64 transition
#    (Trixie) vs older releases.
log "apt-get update"
sudo apt-get update

log "installing apt deps: python3-venv python3-pip libgl1 libglib2.0-0(t64) v4l-utils"
if ! sudo apt-get install -y python3-venv python3-pip libgl1 libglib2.0-0t64 v4l-utils 2>/dev/null; then
  warn "libglib2.0-0t64 not available — falling back to libglib2.0-0 (older Debian/Ubuntu)"
  sudo apt-get install -y python3-venv python3-pip libgl1 libglib2.0-0 v4l-utils
fi

# 2. Pull the canonical requirements.txt from the repo so this script
#    doesn't drift when deps change. Cached at INSTALL_DIR for the
#    eventual `install.sh` run to use.
mkdir -p "$INSTALL_DIR/vendor/wheels"
log "fetching requirements.txt"
curl -fsSL "$REPO_RAW/orangepi/requirements.txt" -o "$INSTALL_DIR/requirements.txt" \
  || fail "couldn't fetch $REPO_RAW/orangepi/requirements.txt"

# 3. pip download into the vendor cache. Forces UTF-8 locale so pip's
#    progress glyphs don't crash on non-tty SSH sessions (the same
#    'charmap codec' issue the bridge worked around).
log "downloading Pi wheels into $INSTALL_DIR/vendor/wheels"
LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 \
  python3 -m pip download --only-binary=:all: \
    -r "$INSTALL_DIR/requirements.txt" \
    -d "$INSTALL_DIR/vendor/wheels"

# 4. Stamp the cache so setup_orangepi.py's pi_wheel_cache_status() check
#    sees a match and skips the bridge step on the next run. Strip CR
#    bytes before hashing — Windows checkouts of requirements.txt have
#    CRLF endings; the laptop normalizes the same way, so this keeps the
#    two hashes equal regardless of which checkout style the team uses.
tr -d '\r' < "$INSTALL_DIR/requirements.txt" \
  | sha256sum | awk '{print $1}' \
  > "$INSTALL_DIR/vendor/wheels/.cache-stamp"

log "done."
log "  apt deps installed."
log "  wheels staged in $INSTALL_DIR/vendor/wheels (\$(ls $INSTALL_DIR/vendor/wheels/*.whl 2>/dev/null | wc -l) files)"
log ""
log "Next step: unplug from internet, plug into the robot network, and"
log "run 'Set up / Update Vision Pi' from the laptop. The wizard will see"
log "the cache stamp and skip the WiFi-bridge step."
