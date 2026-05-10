#!/usr/bin/env bash
# acuity-firstboot.sh — runs once per boot via acuity-firstboot.service.
#
# Single decision: do we have a configured team WiFi (acuity.conf with
# a non-empty SSID), or do we boot into AP-mode setup?
#
# This script is idempotent — it doesn't matter if it runs on every
# boot vs once. The actual mode-switching work is done by
# acuity-wifi-mode.sh, which we delegate to here.

set -euo pipefail

CONF="/boot/firmware/acuity.conf"

log() { logger -t acuity-firstboot "$*"; printf '[acuity-firstboot] %s\n' "$*"; }
fail() { log "FAIL: $*"; exit 1; }

# Helper: read KEY= from acuity.conf, returning empty if missing.
conf_get() {
  local key="$1"
  [ -f "$CONF" ] || return 0
  awk -v k="$key" -F '=' '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    {
      # Strip leading whitespace from the key
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $1)
      if ($1 == k) {
        # Re-join in case the value contained "=" (e.g. base64)
        $1=""; sub(/^=/, "", $0)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
        print
        exit
      }
    }
  ' "$CONF"
}

# 1. Read config (or use defaults if missing).
TEAM="$(conf_get TEAM || true)"
SSID="$(conf_get SSID || true)"
PSK="$(conf_get PSK || true)"
COUNTRY="$(conf_get COUNTRY || true)"
[ -n "$COUNTRY" ] || COUNTRY="US"

log "config: team=${TEAM:-(unset)} ssid=${SSID:-(unset)} country=$COUNTRY"

# 2. Set hostname based on team number. This makes mDNS resolve to
#    `acuity-1279.local` automatically (avahi-daemon picks up the
#    current hostname every time it advertises).
HOSTNAME_CHANGED=0
if [ -n "$TEAM" ]; then
  WANT_HOSTNAME="acuity-${TEAM}"
  CUR_HOSTNAME="$(hostnamectl --static 2>/dev/null || cat /etc/hostname)"
  if [ "$CUR_HOSTNAME" != "$WANT_HOSTNAME" ]; then
    log "hostname: $CUR_HOSTNAME → $WANT_HOSTNAME"
    hostnamectl set-hostname "$WANT_HOSTNAME"
    # Update /etc/hosts so `sudo` doesn't complain about an unresolvable
    # hostname for ~30 s after the change.
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$WANT_HOSTNAME/" /etc/hosts
    HOSTNAME_CHANGED=1
  fi
fi

# (avahi is restarted unconditionally at the end of this script,
# AFTER wifi-mode has fully settled the network. See the bottom of
# this file for the why — short version: avahi is socket-activated
# and races NetworkManager, so we always need to re-sync it once
# the final IP / hostname are in place. Doing it here on hostname
# change isn't enough by itself.)

# 3. Decide WiFi mode.
if [ -z "$SSID" ]; then
  log "no SSID configured → entering AP-mode setup wizard"
  /usr/local/bin/acuity-wifi-mode.sh ap
else
  log "SSID configured ($SSID) → joining as STA (team=${TEAM:-none})"
  # Pass TEAM as the 5th arg so wifi-mode.sh can apply the FRC static
  # IP convention (10.TE.AM.11). With no team, it falls back to DHCP.
  /usr/local/bin/acuity-wifi-mode.sh sta "$SSID" "$PSK" "$COUNTRY" "$TEAM"
fi

# 4. Re-sync avahi-daemon now that the network is in its final state.
#
# Why this is unconditional (not just on hostname change):
# avahi is socket-activated in Pi OS Bookworm, so it starts WAY
# before we run — usually before NetworkManager even brings wlan0
# up. By the time we get here, avahi has already done one of:
#   a) announced under the old hostname (`acuity` or whatever
#      Imager set) — the duplicate-tile-in-Manager bug;
#   b) announced and then watched the interface get torn down +
#      re-IPed when wifi-mode applied the static `10.TE.AM.11/24`
#      — avahi handles the address blip but does NOT re-publish
#      `_acuity._tcp` service records, so the announcement goes
#      stale and Manager loses the device entirely. This is the
#      "I had to restart avahi by hand again" symptom.
#
# A blanket `systemctl restart avahi-daemon` here re-reads the
# current hostname + IP + /etc/avahi/services/*.service and
# re-announces cleanly. Cheap (<1s), idempotent, and runs after
# every boot regardless of whether anything actually changed.
log "syncing avahi-daemon with final network state"
systemctl restart avahi-daemon.service 2>/dev/null \
  || systemctl restart avahi-daemon.socket 2>/dev/null \
  || log "  (avahi restart failed — Manager may not auto-discover this device)"

log "done"
