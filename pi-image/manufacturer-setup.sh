#!/usr/bin/env bash
# Cold Fusion Sight — manufacturer's master-card prep.
#
# Run this on YOUR Pi, on YOUR own WiFi network, when you're prepping
# an SD card you plan to `dd` and ship to other teams. It wraps
# install.sh and adds three "ready to clone" cleanup steps:
#
#   1. Asks if you'd like to forget the WiFi network you used for
#      setup. (You almost always want yes — otherwise every cloned
#      card will silently try to auto-join your home network on the
#      customer's bench, and they'll wonder why the captive portal
#      AP never appears.)
#
#   2. Resets /etc/machine-id so cloned cards regenerate a fresh
#      unique ID on first boot. avahi (mDNS) uses machine-id as part
#      of its conflict-resolution; without this reset, every cloned
#      card shows up as the same identity and they fight over
#      cfsight-NNNN.local.
#
#   3. Clears shell history. Anything you've typed during setup
#      (passwords, debug attempts, IPs of YOUR network, etc.) lives
#      in ~/.bash_history. We blank it before cloning so customers
#      don't accidentally inherit your bench history.
#
# Usage (from a fresh Pi OS Lite that you've already got on internet
# WiFi via Raspberry Pi Imager's advanced settings).
#
# If the repo is *public*, one-liner works:
#   sudo curl -fsSL \
#     https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/pi-image/manufacturer-setup.sh \
#     | sudo bash
#
# If the repo is *private* (raw.githubusercontent.com returns 404 to
# unauthenticated requests), git-clone first using your token, then
# run from the local checkout:
#   GH_TOKEN=ghp_yourtoken
#   git clone "https://${GH_TOKEN}@github.com/ethancroissants/frc-robotcode.git" /tmp/cfs-src
#   sudo bash /tmp/cfs-src/pi-image/manufacturer-setup.sh
#
# When it finishes, run:   sudo shutdown -h now
# Then `dd` the SD card to a master image and clone away.

set -euo pipefail

REPO_RAW="${CFSIGHT_REPO_RAW:-https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master}"
INSTALL_USER="${SUDO_USER:-${USER:-cfsight}}"

log()   { printf '\033[36m[mfg]\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
fail()  { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$EUID" -eq 0 ] || fail "run as root: sudo bash manufacturer-setup.sh"

# === 1. Run the regular install ===
# Two paths:
#   * If we're sitting next to install.sh in a checked-out repo, run
#     that local copy (so manufacturer can iterate on uncommitted
#     changes without re-pushing to GitHub).
#   * Otherwise curl-pipe install.sh from GitHub.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -x "$SCRIPT_DIR/install.sh" ]; then
  log "running local install.sh from $SCRIPT_DIR"
  bash "$SCRIPT_DIR/install.sh"
else
  log "fetching install.sh from $REPO_RAW"
  curl -fsSL "$REPO_RAW/pi-image/install.sh" | bash
fi

# install.sh exits with set -e on any failure, so reaching this line
# means the dashboard service is configured. Now the manufacturer
# cleanup.

echo
log "============================================="
log " Install succeeded. Ready to prep for cloning."
log "============================================="
echo

# === 2. Forget the manufacturer's WiFi ===
# List every saved WiFi connection so the operator can see what's
# about to disappear. nmcli -t = terse output, NAME:TYPE pairs only.
log "Currently-saved WiFi connections on this Pi:"
mapfile -t WIFI_CONNS < <(
  nmcli -t -f NAME,TYPE connection show 2>/dev/null \
    | awk -F: '$2 == "802-11-wireless" {print $1}'
)
if [ "${#WIFI_CONNS[@]}" -eq 0 ]; then
  log "  (none — nothing to forget)"
else
  for c in "${WIFI_CONNS[@]}"; do
    printf '  - %s\n' "$c"
  done
fi

if [ "${#WIFI_CONNS[@]}" -gt 0 ]; then
  echo
  # Read from /dev/tty so this works even when invoked via
  # `curl ... | sudo bash` (which leaves stdin connected to the
  # piped data, not the terminal). /dev/tty is the user's
  # controlling terminal regardless of redirects.
  if [ -t 0 ] || [ -t 1 ] || [ -e /dev/tty ]; then
    read -r -p "Forget all of those WiFi networks? [Y/n] " ANS </dev/tty || ANS=""
  else
    warn "no controlling tty — defaulting to 'yes' (set CFSIGHT_KEEP_WIFI=1 to override)"
    ANS=""
  fi
  case "${CFSIGHT_KEEP_WIFI:-${ANS}}" in
    n|N|no|NO|No|1)
      log "keeping WiFi profiles. (cloned cards will auto-join them — beware)"
      ;;
    *)
      for c in "${WIFI_CONNS[@]}"; do
        log "forgetting: $c"
        nmcli connection delete "$c" >/dev/null 2>&1 || warn "couldn't delete $c"
      done
      # Also nuke the wpa_supplicant fallback file in case anything
      # was set there pre-NetworkManager.
      rm -f /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
      log "WiFi profiles cleared. The next boot will enter AP-mode setup."
      ;;
  esac
fi

# === 3. machine-id reset ===
# avahi uses /etc/machine-id (via libavahi-common) when generating
# its mDNS Unique Identifier. Cloning SD cards with a populated
# machine-id means every clone advertises the same UID, and they
# fight on the LAN. Truncating to empty makes systemd regenerate a
# fresh random ID on first boot of each clone.
log "resetting /etc/machine-id (clones regenerate on first boot)"
truncate -s 0 /etc/machine-id
# /var/lib/dbus/machine-id is conventionally a symlink to /etc on
# modern Debian, but check + repair just in case.
if [ ! -L /var/lib/dbus/machine-id ]; then
  rm -f /var/lib/dbus/machine-id
  ln -sf /etc/machine-id /var/lib/dbus/machine-id
fi

# === 4. Shell history ===
# Don't ship your bench commands in cloned customer cards.
log "clearing shell history"
for u in root cfsight "$INSTALL_USER"; do
  home="$(getent passwd "$u" 2>/dev/null | cut -d: -f6)"
  if [ -n "$home" ] && [ -d "$home" ]; then
    rm -f "$home/.bash_history" "$home/.zsh_history" "$home/.python_history"
  fi
done
# This shell's in-memory history too — won't make it to disk, but
# clean for thoroughness.
history -c 2>/dev/null || true

# === 5. SSH known_hosts / authorized_keys (your laptop's pubkey) ===
# Optional but recommended: clear authorized_keys so customers can't
# reuse your laptop's pubkey on accident, and clear /etc/ssh/ssh_host_*
# so each clone gets fresh host keys (otherwise SSH yells about
# "REMOTE HOST IDENTIFICATION HAS CHANGED" the first time the
# customer connects from a different laptop).
log "clearing SSH host keys (clones regenerate on first boot via systemd-ssh-generator)"
rm -f /etc/ssh/ssh_host_*

if [ -t 0 ] || [ -e /dev/tty ]; then
  read -r -p "Clear authorized_keys for cfsight + $INSTALL_USER too? [y/N] " A2 </dev/tty || A2="n"
else
  A2="n"
fi
case "$A2" in
  y|Y|yes|YES|Yes)
    for u in cfsight "$INSTALL_USER"; do
      home="$(getent passwd "$u" 2>/dev/null | cut -d: -f6)"
      [ -n "$home" ] && rm -f "$home/.ssh/authorized_keys"
    done
    log "authorized_keys cleared."
    ;;
  *)
    log "keeping authorized_keys. (your laptop's key will still work on cloned cards)"
    ;;
esac

# === Done ===
echo
log "============================================="
log " Master card ready for cloning."
log "============================================="
log ""
log "Next steps:"
log "  1. sudo shutdown -h now"
log "  2. Pop the SD card into your laptop."
log "  3. Save the master image:"
log "       sudo dd if=/dev/sdX of=cfsight-master.img bs=4M status=progress"
log "  4. Clone to fresh cards as needed:"
log "       sudo dd if=cfsight-master.img of=/dev/sdY bs=4M status=progress"
log ""
log "Each clone will:"
log "  * generate a fresh machine-id on first boot"
log "  * regenerate SSH host keys on first boot"
log "  * boot into the AP-mode captive portal (CFSight-Setup-XXXX)"
log "  * accept the team's WiFi credentials via the captive portal"
log "  * reboot and dashboard at http://cfsight-NNNN.local:8080/"
log ""
log "If you want to ship a card pre-configured for a specific team,"
log "drop a customized cfsight.conf onto the FAT32 boot partition"
log "of the cloned card before handing it off."
