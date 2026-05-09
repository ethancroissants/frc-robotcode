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
# Self-update:
#   The script re-fetches itself from GitHub on every run before doing
#   anything else, so you don't need to copy commands by hand when this
#   file changes upstream. Set CFR_NO_SELF_UPDATE=1 to skip.
#
# Python upgrade:
#   robotpy-apriltag (the AprilTag detector library PhotonVision uses)
#   only ships wheels for Python 3.10+. If the system Python is older
#   (e.g., Debian 11 / Bullseye ships 3.9), we install a *standalone*
#   Python 3.11 via Astral's `uv` tool. The system Python is never
#   touched — uv stores its Python under ~/.local/share/uv and we just
#   use that for the venv. Set CFR_NO_PY_UPGRADE=1 to skip (you'll fall
#   back to cv2.aruco's worse detector).
#
# Usage (one-liner, from an SSH session on the Pi):
#
#   curl -sSL https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/orangepi/manual_net_install.sh | bash
#
# Or if you already have the script locally:
#
#   bash ~/cold-fusion-sight/manual_net_install.sh
#
# Override knobs (env vars, optional):
#   CFR_REPO_RAW    — base URL for raw.githubusercontent.com lookups.
#   CFR_INSTALL_DIR — where the wheel cache lands (default ~/cold-fusion-sight).
#   CFR_PY_VERSION  — bootstrap Python version (default 3.11).
#   CFR_NO_SELF_UPDATE — set to 1 to skip the upstream-pull step.
#   CFR_NO_PY_UPGRADE  — set to 1 to never install the standalone Python.

set -euo pipefail

REPO_RAW="${CFR_REPO_RAW:-https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master}"
INSTALL_DIR="${CFR_INSTALL_DIR:-$HOME/cold-fusion-sight}"
PY_VERSION="${CFR_PY_VERSION:-3.11}"

# All status output goes to stderr so functions like bootstrap_python can
# write the resolved python path to stdout without log messages getting
# concatenated into it. The user's terminal still sees both streams.
log()  { printf '\033[36m[manual-install]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. Self-update from upstream.
#
# Skipping when:
#   - CFR_NO_SELF_UPDATE=1 is set (e.g., when iterating locally)
#   - CFR_SELF_UPDATED=1 is set (we already self-updated this run; prevents
#     the re-exec'd script from re-checking and looping)
#   - $0 isn't a regular writable file (e.g., piped via curl|bash; in that
#     case we're already running the latest because the curl fetched it)
# ---------------------------------------------------------------------------
maybe_self_update() {
  [ "${CFR_NO_SELF_UPDATE:-0}" = "1" ] && return 0
  [ "${CFR_SELF_UPDATED:-0}"  = "1" ] && return 0
  local self="${BASH_SOURCE[0]:-$0}"
  [ -f "$self" ] || return 0
  [ -w "$self" ] || return 0

  log "checking for newer version of this installer at $REPO_RAW/orangepi/manual_net_install.sh"
  local tmp
  tmp="$(mktemp)" || return 0
  if ! curl -fsSL --max-time 8 -o "$tmp" "$REPO_RAW/orangepi/manual_net_install.sh"; then
    warn "couldn't fetch upstream installer (offline?) — proceeding with local copy"
    rm -f "$tmp"
    return 0
  fi
  if cmp -s "$tmp" "$self"; then
    log "installer is up to date"
    rm -f "$tmp"
    return 0
  fi
  log "newer installer found upstream — replacing $self and re-executing"
  cat "$tmp" > "$self"
  chmod +x "$self"
  rm -f "$tmp"
  export CFR_SELF_UPDATED=1
  exec bash "$self" "$@"
}

# ---------------------------------------------------------------------------
# 1. Python bootstrap.
#
# Echoes the path to a Python ≥ 3.10 interpreter to use for `pip download`
# (and for the eventual venv via install.sh). If the system python3 is new
# enough we just use that; otherwise we install Python via uv (no system
# changes, just a tarball under ~/.local/share/uv).
#
# Caches the resolved interpreter path at $INSTALL_DIR/.python-bin so
# install.sh and future runs can skip the lookup.
# ---------------------------------------------------------------------------
bootstrap_python() {
  local sys_minor
  sys_minor="$(python3 -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)"
  if [ "$sys_minor" -ge 10 ]; then
    echo "python3"
    return 0
  fi

  if [ "${CFR_NO_PY_UPGRADE:-0}" = "1" ]; then
    warn "system python is 3.${sys_minor} (too old for robotpy-apriltag) but CFR_NO_PY_UPGRADE=1 — using system python anyway"
    echo "python3"
    return 0
  fi

  # Cached?
  if [ -f "$INSTALL_DIR/.python-bin" ]; then
    local cached
    cached="$(cat "$INSTALL_DIR/.python-bin")"
    if [ -x "$cached" ]; then
      log "reusing cached bootstrap python: $cached"
      echo "$cached"
      return 0
    fi
  fi

  log "system python is 3.${sys_minor} — bootstrapping Python ${PY_VERSION} via uv (one-time, ~30 MB)" >&2

  # Install uv (Astral's tool that ships standalone Python builds). It's
  # a single static binary; the install script puts it at ~/.local/bin/uv.
  local uv_bin
  uv_bin="$(command -v uv 2>/dev/null || true)"
  if [ -z "$uv_bin" ] && [ -x "$HOME/.local/bin/uv" ]; then
    uv_bin="$HOME/.local/bin/uv"
  fi
  if [ -z "$uv_bin" ]; then
    log "installing uv (Astral) → ~/.local/bin/uv" >&2
    curl -LsSf https://astral.sh/uv/install.sh | sh >&2 \
      || { warn "uv install failed"; return 1; }
    uv_bin="$HOME/.local/bin/uv"
  fi
  [ -x "$uv_bin" ] || { warn "uv binary missing after install"; return 1; }
  export PATH="$HOME/.local/bin:$PATH"

  log "installing Python ${PY_VERSION} via uv" >&2
  "$uv_bin" python install "$PY_VERSION" >&2 \
    || { warn "uv python install failed"; return 1; }
  local py_bin
  py_bin="$("$uv_bin" python find "$PY_VERSION" 2>/dev/null || true)"
  if [ -z "$py_bin" ] || [ ! -x "$py_bin" ]; then
    warn "uv could not provide python ${PY_VERSION}"
    return 1
  fi

  mkdir -p "$INSTALL_DIR"
  echo "$py_bin" > "$INSTALL_DIR/.python-bin"
  log "bootstrap python ready: $py_bin ($("$py_bin" --version 2>&1 | tr -d '\n'))" >&2
  echo "$py_bin"
}

# ---------------------------------------------------------------------------
# Run.
# ---------------------------------------------------------------------------
maybe_self_update "$@"

log "checking internet connectivity"
if ! curl -fsSL --max-time 5 -o /dev/null https://raw.githubusercontent.com/; then
  fail "no internet — plug the Pi into a network that has internet first."
fi

log "apt-get update"
sudo apt-get update

# build-essential + cmake are kept in the apt deps even though the happy
# path uses prebuilt wheels — they cost ~30 MB once and let us pip-install
# packages that *don't* publish wheels for our exact (Python, glibc, arch)
# combo. We've already been bitten by robotpy-apriltag (no Bullseye wheels)
# and pupil-apriltags (no aarch64 wheels at all) and don't want a fresh
# Pi to be wedged again the next time a vendor stops shipping wheels.
log "installing apt deps: python3-venv python3-pip libgl1 libglib2.0-0(t64) v4l-utils ca-certificates curl build-essential cmake"
if ! sudo apt-get install -y python3-venv python3-pip libgl1 libglib2.0-0t64 v4l-utils ca-certificates curl build-essential cmake 2>/dev/null; then
  warn "libglib2.0-0t64 not available — falling back to libglib2.0-0 (older Debian/Ubuntu)"
  sudo apt-get install -y python3-venv python3-pip libgl1 libglib2.0-0 v4l-utils ca-certificates curl build-essential cmake
fi

PYBIN="$(bootstrap_python)" \
  || fail "couldn't bootstrap a working Python — set CFR_NO_PY_UPGRADE=1 to skip and use system python (you'll lose long-range AprilTag detection)"
log "using python: $PYBIN ($("$PYBIN" --version 2>&1 | tr -d '\n'))"

# Pull the canonical requirements.txt from the repo so this script doesn't
# drift when deps change. Cached at INSTALL_DIR for the eventual install.sh
# run to use.
mkdir -p "$INSTALL_DIR/vendor/wheels"
log "fetching requirements.txt"
curl -fsSL "$REPO_RAW/orangepi/requirements.txt" -o "$INSTALL_DIR/requirements.txt" \
  || fail "couldn't fetch $REPO_RAW/orangepi/requirements.txt"

# Make sure pip itself is recent enough to handle modern wheel tags
# (manylinux_2_28, py3.11, etc.). Bullseye's stock pip is 20.x, which
# can't even resolve a number of wheels we need.
log "upgrading pip in the bootstrap python"
LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 \
  "$PYBIN" -m pip install --upgrade pip >/dev/null 2>&1 || true

# pip download into the vendor cache. UTF-8 locale forced so pip's
# progress glyphs don't crash on non-tty SSH sessions.
#
# We deliberately do NOT pass `--only-binary=:all:`: when a package
# doesn't ship a wheel for our (python, glibc, arch) combo, pip falls
# back to fetching its sdist (.tar.gz) and we let install.sh build
# from source on the Pi (build-essential + cmake are now in apt deps).
# Slow on first install (~5-10 min for AprilTag bindings) but unblocks
# the user the moment a vendor stops shipping wheels.
log "downloading Pi wheels (and sdists where wheels aren't available) into $INSTALL_DIR/vendor/wheels"
LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 \
  "$PYBIN" -m pip download \
    -r "$INSTALL_DIR/requirements.txt" \
    -d "$INSTALL_DIR/vendor/wheels"

# Stamp the cache so setup_orangepi.py's pi_wheel_cache_status() check
# sees a match and skips the bridge step on the next run. Strip CR
# bytes before hashing — Windows checkouts of requirements.txt have
# CRLF endings; the laptop normalizes the same way.
tr -d '\r' < "$INSTALL_DIR/requirements.txt" \
  | sha256sum | awk '{print $1}' \
  > "$INSTALL_DIR/vendor/wheels/.cache-stamp"

WHEEL_COUNT="$(ls "$INSTALL_DIR/vendor/wheels/"*.whl 2>/dev/null | wc -l)"
log "done."
log "  apt deps installed."
log "  bootstrap python: $PYBIN"
log "  wheels staged in $INSTALL_DIR/vendor/wheels ($WHEEL_COUNT files)"
log ""
log "Next step: unplug from internet, plug into the robot network, and"
log "run 'Set up / Update Vision Pi' from the laptop. The wizard will see"
log "the cache stamp and skip the WiFi-bridge step."
