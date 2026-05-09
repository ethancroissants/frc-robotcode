#!/usr/bin/env bash
# acuity-wifi-mode.sh — flip wlan0 between AP and STA mode.
#
# Usage:
#   acuity-wifi-mode.sh ap
#       Bring wlan0 up as the open AP "Acuity-Setup-XXXX" with our
#       captive portal. Stops NetworkManager management of wlan0 first.
#
#   acuity-wifi-mode.sh sta <SSID> [<PSK>] [<COUNTRY>]
#       Tear down AP if running, hand wlan0 back to NetworkManager,
#       and connect to <SSID>. Empty PSK = open network.
#
#   acuity-wifi-mode.sh sta+ap <SSID> [<PSK>] [<COUNTRY>]
#       Both at once: STA on wlan0, AP on wlan0_ap (a virtual interface
#       on the same radio). Requires concurrent STA+AP support from
#       the WiFi chipset firmware — Pi Zero 2 W (BCM43436) supports
#       this; many USB dongles don't. Used by the laptop bridge so
#       the wizard can reach the Pi while it joins an internet WiFi.
#
# Called from:
#   - acuity-firstboot.sh on every boot
#   - the captive-portal wizard's "save" handler
#   - the laptop-side bridge over SSH

set -euo pipefail

MODE="${1:-}"
log() { logger -t acuity-wifi-mode "$*"; printf '[acuity-wifi-mode] %s\n' "$*"; }

# Wait until NetworkManager's D-Bus interface answers, or give up
# after ~10s. systemd `After=NetworkManager.service` only blocks until
# the service is Active — the D-Bus listener can lag a beat behind on
# slow Pis, and `nmcli` against a not-yet-ready NM exits with status 8
# ("NetworkManager is not running"). We saw that bite us during boot
# on a Pi Zero 2 W: the script raced NM and exited with set -e before
# wlan0 was configured at all.
wait_for_nm() {
  local i
  for i in $(seq 1 20); do
    if nmcli -t general status >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  log "warning: NetworkManager never came up within 10s; nmcli calls may fail"
  return 1
}

# Compute the AP SSID once. Suffix from MAC so two Pis on the same
# bench show up as distinct APs ("Acuity-Setup-A1B2", "...-C3D4").
ap_ssid() {
  local mac
  mac="$(cat /sys/class/net/wlan0/address 2>/dev/null || echo "00:00:00:00:00:00")"
  local suffix
  suffix="$(echo "$mac" | tr -d ':' | tail -c 5 | tr 'a-f' 'A-F')"
  printf 'Acuity-Setup-%s' "$suffix"
}

stop_ap() {
  systemctl stop acuity-setup-wizard.service 2>/dev/null || true
  pkill -x dnsmasq 2>/dev/null || true
  pkill -x hostapd 2>/dev/null || true
  # wpa_supplicant ALSO has to die — if it stays bound to wlan0, hostapd
  # fails ~100ms after fork with "nl80211: Could not configure driver
  # mode" and our `hostapd -B` parent has already returned 0. That's
  # the silent-success-but-no-AP failure mode that kept biting us.
  pkill -f "wpa_supplicant.*wlan0" 2>/dev/null || true
  ip addr flush dev wlan0 2>/dev/null || true
  ip link delete wlan0_ap 2>/dev/null || true
}

start_ap_on_iface() {
  local iface="$1"
  local AP_SSID
  AP_SSID="$(ap_ssid)"
  log "starting open AP '$AP_SSID' on $iface"

  # Render hostapd config from template.
  local cfg=/run/acuity/hostapd.conf
  local hostapd_log=/var/log/acuity-hostapd.log
  mkdir -p "$(dirname "$cfg")"
  sed "s/{AP_SSID}/$AP_SSID/g" \
    /etc/acuity/hostapd-acuity.conf.template \
    | sed "s/^interface=.*/interface=$iface/" \
    > "$cfg"

  # Aggressive interface cleanup before hostapd. Anything else holding
  # wlan0 (NetworkManager, wpa_supplicant from a previous Imager-set
  # WiFi, leftover hostapd from a half-prior run) makes hostapd fail
  # asynchronously, AFTER `-B` has returned 0 — which used to look like
  # success. Now we force the iface fully idle first.
  if [ "$iface" = "wlan0" ]; then
    nmcli device set "$iface" managed no 2>/dev/null || true
    pkill -f "wpa_supplicant.*$iface" 2>/dev/null || true
    sleep 1
  fi
  rfkill unblock wifi 2>/dev/null || true
  ip link set "$iface" down 2>/dev/null || true
  sleep 0.5
  ip link set "$iface" up
  ip addr flush dev "$iface" 2>/dev/null || true
  ip addr add 192.168.50.1/24 dev "$iface"

  # Render dnsmasq config (template just needs the iface substituted).
  local dconf=/run/acuity/dnsmasq.conf
  sed "s/^interface=.*/interface=$iface/" \
    /etc/acuity/dnsmasq-acuity.conf.template > "$dconf"

  # Launch hostapd. -B daemonizes; the parent returns 0 even if the
  # child dies 100ms later. We capture stderr to a log file and verify
  # the daemon is still alive 2s after fork before claiming success.
  log "launching hostapd (log: $hostapd_log)"
  : > "$hostapd_log"
  if ! hostapd -B -P /run/acuity/hostapd.pid -f "$hostapd_log" "$cfg"; then
    log "hostapd failed to fork. last log lines:"
    tail -20 "$hostapd_log" >&2 || true
    return 1
  fi
  sleep 2
  if ! [ -s /run/acuity/hostapd.pid ] \
     || ! kill -0 "$(cat /run/acuity/hostapd.pid)" 2>/dev/null; then
    log "hostapd died after fork. last log lines:"
    tail -30 "$hostapd_log" >&2 || true
    log "(common cause: wpa_supplicant or NetworkManager still has wlan0;"
    log " run \`pkill -f wpa_supplicant\` and try again)"
    return 1
  fi
  log "hostapd PID $(cat /run/acuity/hostapd.pid) alive after fork — good"

  # dnsmasq runs in foreground by default; -C points at our config which
  # tells it to bind only to wlan0 on 192.168.50.1. systemd-resolved on
  # the standard listen socket is fine because of `bind-interfaces` in
  # the template — dnsmasq won't fight it for :53.
  dnsmasq -C "$dconf" || { log "dnsmasq failed"; return 1; }

  # Bring up the captive portal.
  systemctl start acuity-setup-wizard.service
  log "AP up. Connect to '$AP_SSID' → http://192.168.50.1/"
}

case "$MODE" in
  ap)
    # Take wlan0 out of NetworkManager's hands so hostapd can drive it.
    wait_for_nm || true
    nmcli device set wlan0 managed no 2>/dev/null || true
    rfkill unblock wifi || true
    stop_ap
    start_ap_on_iface wlan0
    ;;

  sta)
    SSID="${2:-}"
    PSK="${3:-}"
    COUNTRY="${4:-US}"
    TEAM="${5:-}"
    [ -n "$SSID" ] || { log "sta mode requires SSID"; exit 1; }

    # FRC static-IP convention: a coprocessor on the team radio gets
    # 10.TE.AM.11/24 with gateway 10.TE.AM.1. Compute it from the team
    # number (if given). Setup-Wizard always passes TEAM so this kicks
    # in for production cards. Pass an empty TEAM to fall back to DHCP
    # (useful for dev Pis joining a home network).
    static_args=()
    if [ -n "$TEAM" ] && [[ "$TEAM" =~ ^[0-9]+$ ]] && [ "$TEAM" -gt 0 ]; then
      te=$(( TEAM / 100 ))
      am=$(( TEAM % 100 ))
      static_ip="10.${te}.${am}.11"
      static_gw="10.${te}.${am}.1"
      log "STA: joining $SSID (country=$COUNTRY, team=$TEAM → $static_ip)"
      static_args=(
        ipv4.method manual
        ipv4.addresses "${static_ip}/24"
        ipv4.gateway "$static_gw"
        ipv4.dns "$static_gw"
      )
    else
      log "STA: joining $SSID (country=$COUNTRY, DHCP — no team number)"
    fi

    wait_for_nm || { log "NetworkManager not ready; aborting STA setup"; exit 1; }
    stop_ap

    # Hand wlan0 back to NetworkManager and add the connection.
    nmcli device set wlan0 managed yes 2>/dev/null || true
    rfkill unblock wifi || true
    iw reg set "$COUNTRY" 2>/dev/null || true

    # Delete a previous "acuity-team" connection so we don't drift if
    # the SSID/PSK changed.
    nmcli connection delete acuity-team 2>/dev/null || true

    # Don't let `set -e` kill the script if `connection add` fails —
    # autoconnect=yes means even a partial config gets retried, and
    # we'd rather log + leave things in a recoverable state than have
    # firstboot exit non-zero and never come back.
    if [ -z "$PSK" ]; then
      nmcli connection add type wifi con-name acuity-team ifname wlan0 \
        ssid "$SSID" -- \
        wifi-sec.key-mgmt none \
        autoconnect yes \
        "${static_args[@]}" \
        || log "nmcli connection add failed (will rely on autoconnect)"
    else
      nmcli connection add type wifi con-name acuity-team ifname wlan0 \
        ssid "$SSID" -- \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
        autoconnect yes \
        "${static_args[@]}" \
        || log "nmcli connection add failed (will rely on autoconnect)"
    fi
    nmcli connection up acuity-team || log "STA up failed (will retry on autoconnect)"
    ;;

  sta+ap)
    # Concurrent STA+AP on a single radio. Used by the laptop bridge so
    # the wizard can keep talking to the Pi over the AP while the Pi
    # briefly joins an internet WiFi for `pip download`.
    #
    # Pi Zero 2 W (BCM43436) firmware supports this; we add a virtual
    # interface wlan0_ap and start hostapd on it while wlan0 stays
    # under NetworkManager for the STA join.
    SSID="${2:-}"
    PSK="${3:-}"
    COUNTRY="${4:-US}"
    [ -n "$SSID" ] || { log "sta+ap requires SSID"; exit 1; }

    log "STA+AP: $SSID over wlan0, AP over wlan0_ap"
    wait_for_nm || { log "NetworkManager not ready; aborting STA+AP"; exit 1; }
    stop_ap

    # Add the virtual AP iface. `iw dev <wlan0> interface add` requires
    # the chipset firmware to advertise multi-interface support — the
    # Pi Zero 2 W's Cypress firmware does. If this fails on a different
    # board we fall back to plain STA so the bridge isn't blocked.
    if ! iw dev wlan0 interface add wlan0_ap type __ap 2>/dev/null; then
      log "concurrent STA+AP not supported on this chipset — falling back to plain STA"
      exec "$0" sta "$SSID" "$PSK" "$COUNTRY"
    fi
    ip link set wlan0_ap address "$(cat /sys/class/net/wlan0/address)"

    # STA up on wlan0 (NetworkManager).
    nmcli device set wlan0 managed yes 2>/dev/null || true
    rfkill unblock wifi || true
    iw reg set "$COUNTRY" 2>/dev/null || true
    nmcli connection delete acuity-bridge 2>/dev/null || true
    if [ -z "$PSK" ]; then
      nmcli connection add type wifi con-name acuity-bridge ifname wlan0 \
        ssid "$SSID" -- wifi-sec.key-mgmt none autoconnect no
    else
      nmcli connection add type wifi con-name acuity-bridge ifname wlan0 \
        ssid "$SSID" -- wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
        autoconnect no
    fi
    nmcli connection up acuity-bridge

    # AP up on wlan0_ap.
    nmcli device set wlan0_ap managed no 2>/dev/null || true
    start_ap_on_iface wlan0_ap
    ;;

  ""|--help|-h)
    sed -n '4,30p' "$0"
    exit 0
    ;;

  *)
    log "unknown mode: $MODE"
    exit 1
    ;;
esac

log "$MODE mode setup complete"
