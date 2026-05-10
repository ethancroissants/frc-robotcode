#!/usr/bin/env bash
# acuity-firstboot.sh — runs once per boot via acuity-firstboot.service.
#
# Decides the network mode for this boot:
#   - wired into the FRC radio (eth0 has a 10.TE.AM.x DHCP lease)
#     → adopt that team number, skip the AP captive portal
#   - SSID configured in /boot/firmware/acuity.conf → join it as STA
#   - neither → bring up the open AP "Acuity-Setup-XXXX" so a laptop
#     can hit the captive-portal wizard
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

# 2. Detect a wired link.
#
# At competition the device is required to be wired to the radio, so
# eth0 already has a DHCP-assigned 10.TE.AM.x address before we run.
# When that's true we don't need the captive portal at all (the laptop
# can reach us straight over the wire) AND we can infer the team
# number from the address even if acuity.conf has no TEAM=.
#
# Probe up to ~10 s for eth0 carrier + DHCP. Carrier alone isn't
# enough — we need a routable address. If nothing shows up in that
# window we fall through to the existing wifi paths below.
ETH_IP=""
ETH_TEAM=""
if [ -e /sys/class/net/eth0 ]; then
  for _ in $(seq 1 20); do
    ETH_IP="$(ip -4 -o addr show dev eth0 scope global 2>/dev/null \
              | awk '{print $4}' | cut -d/ -f1 | head -n1)"
    [ -n "$ETH_IP" ] && break
    sleep 0.5
  done
fi
if [ -n "$ETH_IP" ]; then
  log "eth0 has IPv4 $ETH_IP — wired path is live"
  # FRC convention: 10.TE.AM.0/24 with the radio at .1 and DHCP for
  # everyone else. Parse team from octets 2 and 3 when the address
  # matches. Anything else (192.168.*, etc.) just means we're on a
  # dev/home network — wired is still usable, we just don't get a
  # free team number out of it.
  if [[ "$ETH_IP" =~ ^10\.([0-9]+)\.([0-9]+)\.[0-9]+$ ]]; then
    te="${BASH_REMATCH[1]}"
    am="${BASH_REMATCH[2]}"
    cand=$(( te * 100 + am ))
    # Require team >= 1 so a dev address like 10.0.0.5 (which would
    # parse as "team 0") doesn't get adopted as a real team number.
    if [ "$cand" -ge 1 ]; then
      ETH_TEAM="$cand"
      log "eth0 IP looks like FRC pattern → team $ETH_TEAM"
    fi
  fi
fi

# Effective team: explicit config wins, otherwise use what we sniffed
# off the wire. Downstream code (hostname + wifi static IP) treats
# TEAM as if it had been configured all along.
if [ -z "$TEAM" ] && [ -n "$ETH_TEAM" ]; then
  log "no TEAM in acuity.conf → adopting $ETH_TEAM from ethernet"
  TEAM="$ETH_TEAM"
fi

# 3. Set hostname based on team number. This makes mDNS resolve to
#    `acuity-1279.local` automatically (avahi-daemon picks up the
#    current hostname every time it advertises).
if [ -n "$TEAM" ]; then
  WANT_HOSTNAME="acuity-${TEAM}"
  CUR_HOSTNAME="$(hostnamectl --static 2>/dev/null || cat /etc/hostname)"
  if [ "$CUR_HOSTNAME" != "$WANT_HOSTNAME" ]; then
    log "hostname: $CUR_HOSTNAME → $WANT_HOSTNAME"
    hostnamectl set-hostname "$WANT_HOSTNAME"
    # Update /etc/hosts so `sudo` doesn't complain about an unresolvable
    # hostname for ~30 s after the change.
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$WANT_HOSTNAME/" /etc/hosts
  fi
fi

# (avahi is restarted unconditionally at the end of this script,
# AFTER wifi-mode has fully settled the network. See the bottom of
# this file for the why — short version: avahi is socket-activated
# and races NetworkManager, so we always need to re-sync it once
# the final IP / hostname are in place.)

# 4. Decide WiFi mode.
#
# Truth table:
#   eth up  + SSID set → join SSID (still useful: pit-side wireless)
#   eth up  + no SSID  → leave wifi alone, ethernet is the link
#   eth down + SSID    → join SSID
#   eth down + no SSID → AP-mode captive portal (last resort)
#
# Skipping AP mode when ethernet is up is the whole point of the
# wired path: at competition the device is wired and we'd rather sit
# quietly on the wire than spam an AP nobody asked for.
if [ -n "$SSID" ]; then
  log "SSID configured ($SSID) → joining as STA (team=${TEAM:-none})"
  # Pass TEAM as the 5th arg so wifi-mode.sh can apply the FRC static
  # IP convention (10.TE.AM.11). With no team, it falls back to DHCP.
  /usr/local/bin/acuity-wifi-mode.sh sta "$SSID" "$PSK" "$COUNTRY" "$TEAM"
elif [ -n "$ETH_IP" ]; then
  log "ethernet is up and no SSID configured → skipping wifi entirely"
else
  log "no SSID and no ethernet → entering AP-mode setup wizard"
  /usr/local/bin/acuity-wifi-mode.sh ap
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
