================================================================
 Cold Fusion Sight — Vision Pi
================================================================

If this is your first time booting the Pi, you have TWO ways to get
it on your robot's WiFi:

----------------------------------------------------------------
OPTION 1 — Captive-portal setup (no laptop required)
----------------------------------------------------------------
  1. Plug a USB camera into the Pi.
  2. Plug in power.
  3. Wait ~60 seconds for the LEDs to settle.
  4. On your phone, look for an open WiFi network called
        CFSight-Setup-XXXX
     (XXXX is the last 4 hex digits of the Pi's WiFi MAC, so you
      can have multiple Pis on the bench without collisions).
  5. Connect to it. Your phone should automatically pop a setup
     page (iOS / Android both detect us as a captive portal).
     If it doesn't, open `http://192.168.50.1/` in any browser.
  6. Enter your team number, robot WiFi SSID, and password.
     Hit Save. The Pi reboots and joins your robot WiFi.
  7. From any device on the robot WiFi, open
        http://cfsight-NNNN.local:8080/
     where NNNN is your team number.

----------------------------------------------------------------
OPTION 2 — Pre-configure on the SD card (skip the AP entirely)
----------------------------------------------------------------
  1. Plug the SD card into your laptop. The boot partition is
     FAT32 — it'll mount on Windows / macOS / Linux.
  2. Open `cfsight.conf.example`, fill in TEAM / SSID / PSK,
     save it as `cfsight.conf` (no .example suffix).
  3. Eject, plug into the Pi, power on.
  4. ~30 seconds later the Pi is on your robot WiFi at
        http://cfsight-NNNN.local:8080/

----------------------------------------------------------------
TROUBLESHOOTING
----------------------------------------------------------------
* Can't see CFSight-Setup-XXXX → wait 90s, the Pi takes a moment
  to bring up hostapd. If still nothing, check the camera is
  USB-OTG-attached (a non-OTG cable won't work on Pi Zero 2 W).
* Joined the AP, captive portal didn't pop → open
  `http://192.168.50.1/` directly.
* `cfsight-NNNN.local` doesn't resolve → on Windows install
  Bonjour Print Services (free from apple.com); modern Win 10+
  has it built in.
* Lost the password / want to redo setup → delete `cfsight.conf`
  from the SD card's boot partition and reboot. The Pi falls
  back to AP mode.

Default user / password (SSH): cfsight / cfsight
CHANGE THIS BEFORE PUTTING THE PI ON A FIELD NETWORK.

  ssh cfsight@cfsight-NNNN.local
  passwd

Source code + docs: github.com/ethancroissants/frc-robotcode
