#!/usr/bin/env bash
# acuity-status-led.sh — drive the Pi's onboard ACT LED to indicate
# device state at a glance, no laptop required.
#
# Patterns, by state name (state file: /run/acuity/status, one word):
#
#   boot        | system is booting / firstboot still running
#               | → slow "heartbeat" pulse (one beat / 1.5 s)
#   ap          | AP-mode captive portal active, waiting for setup
#               | → rapid blink (5 Hz)
#   sta-connecting
#               | joining a configured team WiFi
#               | → medium blink (1.25 Hz)
#   connected   | on a team WiFi / radio link, dashboard healthy
#               | → solid on
#   wired       | live on eth0 (FRC ethernet path)
#               | → two short pulses + long on (every ~3 s) so it
#               |   visually differs from plain "connected"
#   update      | firmware update in progress (the bridge update flow
#               | sets this before curl|bash)
#               | → triple-blip pattern (three quick blinks, pause)
#   error       | a critical service failed (systemd OnFailure hooks
#               | flip the state here)
#               | → Morse SOS  · · · — — — · · ·
#   off         | force the LED dark (e.g. nighttime matches)
#               | → solid off
#
# Setting state from any other script:
#   /usr/local/bin/acuity-status <state>
#
# The LED file is /sys/class/leds/ACT/brightness on most Pi OS builds
# (Pi Zero 2 W, Pi 3, Pi 4); on some images it's exposed as `led0`.
# We probe both and bail with a clear log if neither exists — we
# never want the daemon dying silently and leaving the LED stuck.
#
# Note on boot-time failures we CAN'T influence: if the SoC can't
# load start.elf or the kernel, the GPU firmware itself blinks the
# LED in fixed patterns (4 long = start.elf missing, 7 = kernel
# missing, etc — see Raspberry Pi documentation). Those run before
# any userspace exists. The "error" state we drive below is for
# failures that happen AFTER we've taken control of the LED, e.g.
# acuity-dashboard.service crashing or firstboot hitting set -e.

set -uo pipefail

STATE_FILE="${ACUITY_LED_STATE_FILE:-/run/acuity/status}"

log() { logger -t acuity-status-led "$*"; printf '[acuity-status-led] %s\n' "$*"; }

# --- Find the LED ---------------------------------------------------
LED_DIR=""
for candidate in /sys/class/leds/ACT /sys/class/leds/led0 \
                 /sys/class/leds/PWR /sys/class/leds/mmc0::; do
  if [ -d "$candidate" ] && [ -w "$candidate/brightness" ]; then
    LED_DIR="$candidate"
    break
  fi
done

if [ -z "$LED_DIR" ]; then
  log "no writable LED found under /sys/class/leds — daemon exiting cleanly"
  # Sleep forever so systemd doesn't treat exit-0 as "service did
  # nothing, restart me." We're a no-op on this hardware tier; that's
  # not an error.
  exec sleep infinity
fi

log "driving $LED_DIR"

MAX_BRIGHT=1
if [ -r "$LED_DIR/max_brightness" ]; then
  MAX_BRIGHT="$(cat "$LED_DIR/max_brightness" 2>/dev/null || echo 1)"
fi

# Take the LED away from whatever kernel trigger owns it now (mmc0
# activity, default-on, etc). Setting trigger=none gives us full
# control via brightness writes.
echo none > "$LED_DIR/trigger" 2>/dev/null || true

led_on()  { echo "$MAX_BRIGHT" > "$LED_DIR/brightness" 2>/dev/null || true; }
led_off() { echo 0             > "$LED_DIR/brightness" 2>/dev/null || true; }

# --- Pattern primitives ---------------------------------------------
# Each pattern function plays ONE cycle and returns. The outer loop
# re-reads the state file between cycles so transitions feel snappy.
# `s` is shorthand for sleep with subsecond support.
s() { sleep "$1"; }

pat_boot() {
  # Heartbeat — one quick double-pulse, then a long off.
  led_on; s 0.08
  led_off; s 0.10
  led_on; s 0.08
  led_off; s 1.20
}

pat_ap() {
  # Rapid blink — eye-catching so the user spots "this is the one
  # asking for setup" across a row of devices on a bench.
  led_on;  s 0.10
  led_off; s 0.10
}

pat_sta_connecting() {
  led_on;  s 0.40
  led_off; s 0.40
}

pat_connected() {
  led_on
  # Long sleep to keep the brightness write rate near-zero. The state
  # checker still wakes between cycles to notice a transition.
  s 1.50
}

pat_wired() {
  # Two short pulses + a long on. Visually says "more than connected";
  # we use it for the wired-radio path so an inspector can see at a
  # glance whether a device is using its ethernet or its WiFi link.
  led_on;  s 0.08
  led_off; s 0.14
  led_on;  s 0.08
  led_off; s 0.14
  led_on;  s 1.20
  led_off; s 0.40
}

pat_update() {
  # Triple blip — communicates "busy doing something deliberate"
  # without looking like an error.
  for _ in 1 2 3; do
    led_on;  s 0.08
    led_off; s 0.12
  done
  s 0.70
}

# Morse timing. Dot = 1 unit, dash = 3 units, intra-letter gap = 1,
# inter-letter gap = 3, inter-word gap = 7. UNIT_S is the dot length;
# 0.18 s gives a readable SOS in ~3 s per cycle.
UNIT_S=0.18
dot()  { led_on;  s "$UNIT_S"; led_off; s "$UNIT_S"; }
dash() { led_on;  s "$(awk "BEGIN{print $UNIT_S * 3}")"; led_off; s "$UNIT_S"; }
gap_letter() { s "$(awk "BEGIN{print $UNIT_S * 2}")"; }   # already 1 from prev gap, need +2 more for total 3
gap_word()   { s "$(awk "BEGIN{print $UNIT_S * 6}")"; }   # already 1, +6 = 7

pat_error() {
  # S = . . .
  dot; dot; dot
  gap_letter
  # O = — — —
  dash; dash; dash
  gap_letter
  # S = . . .
  dot; dot; dot
  gap_word
}

pat_off() {
  led_off
  s 1.00
}

# --- State machine --------------------------------------------------
current_state=""

play_one_cycle() {
  case "$1" in
    boot)            pat_boot ;;
    ap)              pat_ap ;;
    sta-connecting)  pat_sta_connecting ;;
    connected)       pat_connected ;;
    wired)           pat_wired ;;
    update)          pat_update ;;
    error)           pat_error ;;
    off)             pat_off ;;
    *)
      # Unknown state name — fall back to a slow blink so a typo in a
      # caller's `acuity-status <typo>` is visible rather than silent.
      led_on; s 0.05; led_off; s 1.95
      ;;
  esac
}

read_state() {
  if [ -r "$STATE_FILE" ]; then
    # Trim whitespace + take the first word so users can stash a
    # comment after the state name without confusing us.
    awk 'NR==1 {print $1; exit}' "$STATE_FILE" 2>/dev/null
  else
    # Default state until firstboot decides otherwise.
    echo "boot"
  fi
}

# Graceful exit: restore the kernel's default trigger on the way out
# so a `systemctl stop` doesn't leave the LED frozen in whatever the
# last pattern wrote.
cleanup() {
  log "exiting; restoring default trigger"
  echo "mmc0" > "$LED_DIR/trigger" 2>/dev/null \
    || echo "default-on" > "$LED_DIR/trigger" 2>/dev/null \
    || true
}
trap cleanup EXIT INT TERM

mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true

while :; do
  next="$(read_state)"
  if [ "$next" != "$current_state" ]; then
    log "state: ${current_state:-<none>} → $next"
    current_state="$next"
  fi
  play_one_cycle "$current_state"
done
