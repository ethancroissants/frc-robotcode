# Cold Fusion Sight — Vision Pi setup

A complete Pi-Zero-2-W (or Pi 4 / Pi 5) vision coprocessor — camera +
AprilTag detector + dashboard — that boots into either:

* **STA mode** joining your team WiFi, dashboard at `http://cfsight-NNNN.local:8080/`
* **AP mode** "CFSight-Setup-XXXX" with a captive-portal wizard for
  first-time WiFi configuration (no laptop tooling required)

Single SD card, single setup script, suitable for mass production by
cloning a working SD card.

## How to build a working SD card

### 1. Flash stock Raspberry Pi OS Lite (64-bit, Bookworm)

Use **Raspberry Pi Imager**. Pick "Raspberry Pi OS Lite (64-bit)" under
Other → Pi OS (other). In Imager's *Advanced settings* (gear icon), set:

* **Hostname** — anything (we'll override based on team number later)
* **SSH** — enable, with your laptop's pubkey or a password
* **WiFi** — set to your home/laptop WiFi network. **Temporary** — just
  needs to work long enough for the install script to apt-install +
  pip-install. We replace it during cloning.
* **User** — `cfsight` / a password you remember (this stays as the
  Linux login user)

Flash it. Plug into the Pi. Power on. Wait ~30 s for first boot.

### 2. SSH in + run the install script

```sh
ssh cfsight@<pi-ip>     # find via your router's DHCP table or `arp -a`
sudo curl -fsSL \
   https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/pi-image/install.sh \
   | sudo bash
```

Takes ~5-10 minutes on a Pi Zero 2 W (mostly pip installing OpenCV +
pyapriltags wheels). Output ends with a "next steps" summary.

### 3. (Optional) pre-configure team WiFi via boot partition

If you know the team WiFi credentials and want to skip the AP wizard:

```sh
sudo nano /boot/firmware/cfsight.conf.example
# Edit TEAM=, SSID=, PSK=, save as cfsight.conf (drop the .example)
sudo cp /boot/firmware/cfsight.conf.example /boot/firmware/cfsight.conf
```

Or do this from your laptop after shutdown — `/boot/firmware/` is a
FAT32 partition that mounts on Windows / macOS / Linux.

### 4. Reboot to verify

```sh
sudo reboot
```

After reboot, **either**:

* If `cfsight.conf` is set → the Pi joins the team WiFi. Browse to
  `http://cfsight-NNNN.local:8080/`.
* If not set → the Pi puts up an open AP **`CFSight-Setup-XXXX`**.
  Connect from a phone; iOS / Android pop a setup form
  automatically (or open `http://192.168.50.1/`). Fill in team #,
  SSID, password, hit save. The Pi reboots and joins.

### 5. (Mass production) — use `manufacturer-setup.sh` instead of `install.sh`

If you're prepping a card to **clone for shipping**, run
`manufacturer-setup.sh` rather than `install.sh`. It does everything
`install.sh` does, then adds a "ready to clone" cleanup pass.

If the repo is **public**:

```sh
sudo curl -fsSL \
   https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/pi-image/manufacturer-setup.sh \
   | sudo bash
```

If the repo is **private** (raw.githubusercontent.com returns 404 to
unauthenticated requests, even though the URL loads in your browser),
clone with your token first:

```sh
GH_TOKEN=ghp_yourtoken
git clone "https://${GH_TOKEN}@github.com/ethancroissants/frc-robotcode.git" /tmp/cfs-src
sudo bash /tmp/cfs-src/pi-image/manufacturer-setup.sh
```

(The token only stays in `/tmp/cfs-src/.git/config` for the duration
of this run; the master image won't ship it because we delete `/tmp`
contents at shutdown anyway. If you want extra paranoia, `rm -rf
/tmp/cfs-src` after the script finishes and before `dd`.)

What the cleanup adds on top of `install.sh`:

| Step | Why |
|---|---|
| Forget your bench WiFi (with confirmation) | Otherwise every cloned card silently auto-joins your home WiFi instead of going to AP-mode setup |
| Reset `/etc/machine-id` (truncated; regenerated on first boot of each clone) | Without this, every clone shares the same mDNS unique-id and they fight over `cfsight-NNNN.local` |
| Delete `/etc/ssh/ssh_host_*` | Each clone regenerates fresh SSH host keys — no "REMOTE HOST IDENTIFICATION HAS CHANGED" surprises |
| Clear shell history (`~/.bash_history`, `~/.zsh_history`, `~/.python_history` for root + cfsight + your install user) | Don't ship your bench commands |
| Optional: clear `authorized_keys` (asks first) | Stops your laptop's SSH key from working on cloned cards |

After it finishes, shut down + clone:

```sh
sudo shutdown -h now

# On your laptop:
sudo dd if=/dev/sdX of=cfsight-master.img bs=4M status=progress

# For each customer card:
sudo dd if=cfsight-master.img of=/dev/sdY bs=4M status=progress
```

Each clone boots into AP mode (`CFSight-Setup-XXXX`) by default; the
team configures their own WiFi via the captive portal. To ship a
card pre-configured for a specific team, mount the cloned card's
FAT32 boot partition and drop a team-specific `cfsight.conf` onto it
before handing the card off.

> **Don't run `manufacturer-setup.sh` on your own dev Pi** — you'll
> have to re-enter your WiFi password to get back online afterwards.
> Use plain `install.sh` for dev / iterating; `manufacturer-setup.sh`
> only for cards going out the door.

## What lives where

| Path on the Pi | Purpose |
|---|---|
| `/opt/cfsight/sight/` | Dashboard service (the FastAPI camera + tag UI) |
| `/opt/cfsight/setup-wizard/` | Captive-portal app, AP-mode only |
| `/opt/cfsight/.venv/` | Python venv with all wheels pre-installed |
| `/etc/systemd/system/cfsight-firstboot.service` | Runs every boot; decides STA vs AP |
| `/etc/systemd/system/cold-fusion-sight.service` | The dashboard service |
| `/etc/systemd/system/cfsight-setup-wizard.service` | Captive portal, started by AP-mode helper |
| `/usr/local/bin/cfsight-firstboot.sh` | Runs at boot; sets hostname + delegates to wifi-mode |
| `/usr/local/bin/cfsight-wifi-mode.sh` | `ap` / `sta` / `sta+ap` switcher |
| `/etc/cfsight/*.conf.template` | hostapd / dnsmasq templates rendered at AP-mode time |
| `/boot/firmware/cfsight.conf` | Per-Pi config (FAT32 — editable from any laptop) |

## Switching between modes after install

```sh
# Force back into AP setup mode
sudo rm /boot/firmware/cfsight.conf
sudo reboot

# Live, no reboot — switch wlan0 to the AP
sudo cfsight-wifi-mode.sh ap

# STA + AP simultaneously (Pi joins an internet WiFi while keeping
# the captive portal up — useful when the Pi needs internet briefly
# for an update)
sudo cfsight-wifi-mode.sh sta+ap "MyHomeWiFi" "homepassword" US
```

## Updating an already-deployed Pi

`install.sh` is idempotent — re-running pulls the latest code, refreshes
the venv, reinstalls systemd units. Call it again whenever you want
to update.

The wrinkle: `install.sh` needs the Pi to have internet (it
apt-installs and pip-installs). After deployment your Pi is on **team
WiFi**, which usually has no internet. Three ways to handle that:

### A. Move the Pi to an internet network (easiest)

Physically pop the Pi off the robot, plug it into a network with
internet (your home WiFi, a phone hotspot, your laptop's hotspot —
anything). It'll re-join via the saved profile from when you first set
it up.

```sh
ssh cfsight@cfsight-NNNN.local
sudo curl -fsSL \
   https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/pi-image/install.sh \
   | sudo bash
sudo systemctl restart cold-fusion-sight
```

When you put it back near the robot, it auto-reconnects to team WiFi.

### B. Concurrent STA + AP (don't move the Pi)

The Pi Zero 2 W's BCM43436 chipset supports running as **STA on one
WiFi** *and* **AP on its own SSID** simultaneously, on a single radio.
This means the Pi can briefly hop onto an internet WiFi for the update
while still being reachable from your phone / laptop via the
`CFSight-Setup-XXXX` AP.

```sh
# On the Pi (still SSH'd in over team WiFi):
sudo /usr/local/bin/cfsight-wifi-mode.sh sta+ap "MyInternetWiFi" "password"

# Your existing SSH connection over team WiFi will drop here — the
# Pi just left team WiFi for the internet WiFi. Reconnect via the
# AP that's now up:

# On your phone or laptop:
#   1. Connect to the open AP "CFSight-Setup-XXXX"
#   2. ssh cfsight@192.168.50.1
#   3. sudo curl -fsSL .../install.sh | sudo bash

# When done, switch the Pi back to team WiFi:
ssh cfsight@192.168.50.1
sudo /usr/local/bin/cfsight-wifi-mode.sh sta "TeamSSID" "..."
```

What this does NOT support: keeping the team-WiFi STA connection
alive *and* joining a second STA. That'd require a second radio
(Pi Zero 2 W has one). If you need to update without moving the Pi
and without losing team-WiFi visibility, plug a USB WiFi dongle in
and use the dongle for the bridge — the Pi will see it as `wlan1`
and you can mix-and-match. Out of scope for the standard install
but easy to wire up if you ever need it.

### C. Just don't update from competition

In practice: 99% of updates happen at home where the Pi has internet
already. Plan ahead and update the night before competition.

## File structure (this directory)

```
pi-image/
├── README.md                       (this file)
├── install.sh                      (run on the Pi to set everything up)
├── files/                          (mirror of install destinations)
│   ├── boot/                       → /boot/firmware/
│   │   ├── README-CFSIGHT.txt
│   │   └── cfsight.conf.example
│   ├── etc/
│   │   ├── cfsight/                → /etc/cfsight/
│   │   │   ├── dnsmasq-cfsight.conf.template
│   │   │   └── hostapd-cfsight.conf.template
│   │   └── systemd/system/         → /etc/systemd/system/
│   │       ├── cfsight-firstboot.service
│   │       ├── cfsight-setup-wizard.service
│   │       └── cold-fusion-sight.service
│   └── usr/local/bin/              → /usr/local/bin/
│       ├── cfsight-firstboot.sh
│       └── cfsight-wifi-mode.sh
└── setup-wizard/                   → /opt/cfsight/setup-wizard/
    └── server.py                   (FastAPI captive portal)
```

`install.sh` reads from `files/` at install time and copies into the
matching destination paths. Mirroring keeps the layout obvious — what
you see in the repo is what ends up on the Pi.
