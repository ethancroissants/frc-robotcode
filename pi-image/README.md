# Cold Fusion Sight — Pi image

A complete bootable image for **Raspberry Pi Zero 2 W** (or Pi 4 / Pi 5,
since it's just `arm64` Raspberry Pi OS Lite under the hood) that comes
up the moment you plug in a camera and power. No SSH, no apt, no `pip
install`, no laptop wizard required.

## What ends up on the Pi

* Raspberry Pi OS Lite (Bookworm, arm64)
* The full Cold Fusion Sight service in `/opt/cfsight/sight/`, running
  as the `cfsight` user, on TCP 8080
* A **first-boot configurator** (`cfsight-firstboot.service`) that runs
  on every boot and decides whether to bring WiFi up as STA or AP
* A **captive-portal setup wizard** (FastAPI on port 80, AP-mode only)
  that walks the operator through entering team WiFi credentials
* Avahi / mDNS so `cfsight-NNNN.local` resolves on every modern client
* The hostname auto-derived from the team number every boot

## Two ways to configure

### Easy (no laptop): captive-portal AP

1. Power the Pi on with no SD-card pre-config.
2. From your phone, look for an **open** WiFi network called
   `CFSight-Setup-XXXX` (XXXX is the last 4 hex digits of the Pi's
   MAC, so multiple Pis on a bench don't collide).
3. Connect. iOS / Android pop the captive portal automatically; if
   they don't, open `http://192.168.50.1/` in any browser.
4. Form: team number, your robot WiFi SSID, password. Submit.
5. The Pi reboots, joins your robot WiFi, and shows up at
   `http://cfsight-NNNN.local:8080/`.

### Pre-configured (faster for mass production)

Edit `/boot/firmware/cfsight.conf` on the SD card from your laptop
**before** plugging it into the Pi. The boot partition is FAT32 — it
mounts on Windows/macOS/Linux. Set:

```
TEAM=1279
SSID=YourRobotWiFi
PSK=yourpassword
COUNTRY=US
```

Boot the Pi. It joins the WiFi directly, no AP step. Same dashboard URL.

## Getting the image

You have **three** options, in order of how much work you want to do:

### Option A — Run the GitHub Actions build (no local Linux needed)

The build is **manual only** — open it explicitly when you want a new
image:

1. Open the project's **Actions** tab on GitHub.
2. Pick "Build Pi image" → "Run workflow" (top-right green button) →
   optionally enter a version string → Run.
3. Tick **"Also publish a GitHub Release"** if you want the resulting
   `.img.xz` attached to a public Release page (so other teams can
   download it without needing GitHub access). Otherwise it's just an
   artifact on the run page.
4. ~30 minutes later the run page has the `.img.xz` as a downloadable
   workflow artifact (kept for 90 days). If you ticked the Release
   option, it also shows up on the **Releases** page tagged
   `v<version>`.

### Option B — Build locally on a Linux box

Useful for offline builds or when you're iterating on the image.

```sh
# Linux only (any modern distro — pi-gen needs a Linux kernel for the
# loop devices and binfmt qemu chroot). macOS / Windows users: use a
# VM, WSL2, or just lean on Option A/B above.
cd pi-image
./build.sh        # auto-installs missing host deps via apt-get
# ~15-30 min on a modern laptop. Output:
#   pi-image/out/cfsight-0.1.0-arm64.img.xz
```

Then flash with **Raspberry Pi Imager** → "Use custom image" → that
file. Imager's *Advanced settings* panel can pre-populate WiFi for
you too (they write to `wpa_supplicant.conf`, which our first-boot
script reads alongside our own `cfsight.conf`).

### What's in the image, in detail

```
/opt/cfsight/
├── sight/                       (the dashboard service)
├── setup-wizard/                (the AP-mode captive portal)
├── firstboot/                   (one-shot boot logic)
├── .venv/                       (pre-built python venv with all wheels)
└── requirements.txt

/etc/cfsight/
├── hostapd-cfsight.conf.template
└── dnsmasq-cfsight.conf.template

/etc/systemd/system/
├── cfsight-firstboot.service    (oneshot, every boot)
├── cfsight-setup-wizard.service (AP-mode only)
└── cold-fusion-sight.service    (the dashboard, always)

/boot/firmware/
├── cfsight.conf.example         (template — copy to cfsight.conf)
└── README-CFSIGHT.txt           (operator-facing instructions)

/usr/local/bin/
├── cfsight-firstboot.sh         (the brain — STA vs AP decision)
└── cfsight-wifi-mode.sh         (low-level WiFi mode flips)
```

## Switching modes after first boot

```sh
# Force back into AP mode for re-config
ssh cfsight@cfsight-NNNN.local 'sudo rm /boot/firmware/cfsight.conf && sudo reboot'

# Or live, no reboot
ssh cfsight@cfsight-NNNN.local 'sudo cfsight-wifi-mode.sh ap'

# Concurrent STA+AP (for the laptop bridge — Pi joins an internet
# WiFi while keeping its setup AP up so the laptop can monitor)
ssh cfsight@cfsight-NNNN.local \
    'sudo cfsight-wifi-mode.sh sta+ap "MyHomeWiFi" "password" US'
```

## Default credentials

* SSH user: `cfsight`
* SSH password: `cfsight`
* **Change this** before deploying. `passwd` from an SSH session.
* Optionally set `NEW_USERNAME=` / `NEW_PASSWORD=` in `cfsight.conf`
  to have the first-boot script rotate them automatically.

## Mass production

For shipping pre-configured kits to other teams:

```sh
# 1. Build the image once (you get the .img.xz)
./pi-image/build.sh

# 2. Per Pi: flash the .img.xz to an SD card, then drop a customized
#    cfsight.conf onto the boot partition with that team's number /
#    SSID. Two scripted commands and you're done.
xzcat pi-image/out/cfsight-0.1.0-arm64.img.xz | sudo dd of=/dev/sdX bs=4M status=progress
sudo mount /dev/sdX1 /mnt   # boot partition
sudo cp tools/customer-1234/cfsight.conf /mnt/cfsight.conf
sudo sync && sudo umount /mnt
```

The team plugs the card in, powers on, and the dashboard lives at
`cfsight-1234.local:8080` 30 seconds later. Zero touch.
