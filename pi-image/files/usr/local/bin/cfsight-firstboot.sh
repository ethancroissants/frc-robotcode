#!/usr/bin/env bash
# cfsight-firstboot.sh — runs once per boot via cfsight-firstboot.service.
#
# Single decision: do we have a configured team WiFi (cfsight.conf with
# a non-empty SSID), or do we boot into AP-mode setup?
#
# This script is idempotent — it doesn't matter if it runs on every
# boot vs once. The actual mode-switching work is done by
# cfsight-wifi-mode.sh, which we delegate to here.

set -euo pipefail

CONF="/boot/firmware/cfsight.conf"

log() { logger -t cfsight-firstboot "$*"; printf '[cfsight-firstboot] %s\n' "$*"; }
fail() { log "FAIL: $*"; exit 1; }

# Helper: read KEY= from cfsight.conf, returning empty if missing.
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
#    `cfsight-1279.local` automatically (avahi-daemon picks up the
#    current hostname every time it advertises).
if [ -n "$TEAM" ]; then
  WANT_HOSTNAME="cfsight-${TEAM}"
  CUR_HOSTNAME="$(hostnamectl --static 2>/dev/null || cat /etc/hostname)"
  if [ "$CUR_HOSTNAME" != "$WANT_HOSTNAME" ]; then
    log "hostname: $CUR_HOSTNAME → $WANT_HOSTNAME"
    hostnamectl set-hostname "$WANT_HOSTNAME"
    # Update /etc/hosts so `sudo` doesn't complain about an unresolvable
    # hostname for ~30 s after the change.
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$WANT_HOSTNAME/" /etc/hosts
  fi
fi

# 3. Decide WiFi mode.
if [ -z "$SSID" ]; then
  log "no SSID configured → entering AP-mode setup wizard"
  /usr/local/bin/cfsight-wifi-mode.sh ap
else
  log "SSID configured ($SSID) → joining as STA"
  /usr/local/bin/cfsight-wifi-mode.sh sta "$SSID" "$PSK" "$COUNTRY"
fi

log "done"
