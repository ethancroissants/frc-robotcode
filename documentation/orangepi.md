# Vision Pi (Orange Pi 5) — Setup Guide

The Pi runs the camera + the click-to-aim web page. The rio runs the
robot. They share the robot's network and talk over NetworkTables.

If you're new to this — **read the next section first.** It's the part
that's confusing the first time, and the rest of the doc assumes you've
seen it.

---

## How this actually works (read this)

### The network

Every FRC robot has the same network shape:

```
                Driver laptop (DHCP)
                       │
                   robot WiFi
                       │
                ┌──────┴──────┐
                │   Radio     │   10.TE.AM.1     ← always
                └──┬────────┬─┘
                   │        │
                Ethernet  Ethernet
                   │        │
              ┌────▼──┐  ┌──▼──────────┐
              │ rio   │  │ Orange Pi 5 │
              │ .2    │  │ .11         │   ← we pin this
              └───────┘  └─────────────┘
```

For team **1279**, that means:

| Device              | IP          | Notes                              |
|---------------------|-------------|------------------------------------|
| Radio               | 10.12.79.1  | Set by the radio image             |
| **roboRIO**         | 10.12.79.2  | Set by the FRC NI image, hardcoded |
| Driver laptop       | 10.12.79.5+ | DHCP, varies                       |
| **Vision Pi**       | 10.12.79.11 | Pinned by `install.sh` (this repo) |

You don't pick these. The radio + rio + image all assume them. We just
pick `.11` for the Pi because that's the standard "first coprocessor"
slot in FRC, and we *pin* it during Pi setup so it never moves.

> "What if I'm not on team 1279?" Edit `pyproject.toml` /
> `.wpilib/wpilib_preferences.json` to set your team. The setup script
> will read it and pin the Pi to `10.<TE>.<AM>.11` automatically.

### The boot sequence

Power flows on. From there, with **zero buttons pressed:**

1. Radio comes up (`10.TE.AM.1`).
2. Pi boots Armbian → `cold-fusion-sight.service` autostarts → web
   server listens on `:8080` → tries to reach the rio over NT.
3. rio boots → robot code starts → `orangepi_pusher.py` runs in a
   daemon thread. It looks at `pi_target.json` (which got deployed
   along with `robot.py`), finds the Pi at `10.TE.AM.11`, and:
   - hashes the deployed `orangepi/` files
   - SSHes the Pi as `orangepi` (using a key set up at provisioning time)
   - if the hash differs from what's on the Pi, tar-pipes the new
     files, writes the hash, and `systemctl restart cold-fusion-sight`
   - if the hashes match, does nothing.
4. Pi's web server is now showing the latest UI; rio's robot code is
   running. They've found each other over NT and the dashboard pill
   says **CONNECTED**.

That's it. **You never need to deploy the Pi separately.** Press the
single **Deploy to Robot** button on the laptop → rio gets the code →
on next robot boot the rio pushes the relevant files to the Pi. Done.

### How they talk

Two channels:

- **NetworkTables (live state).** rio publishes RPS / dial / predicted
  / LaserCAN / button state on `/SmartDashboard/...`. The Pi's web app
  is an NT4 *client* (same protocol Elastic uses) and reads them. When
  you click the camera in the browser, the Pi writes
  `/Sight/Aim/{X,Y,RequestId}` and the rio's `AutoAim` command picks
  it up.

- **SSH (file pushes).** Used only for `orangepi_pusher.py` (rio →
  Pi) shipping new files when you redeploy. Not used at runtime.

### Where you open the UI

Three URLs, all show the same page:

- `http://10.12.79.11:8080/` — the static IP, always works on the
  robot's network.
- `http://orangepi.local:8080/` — convenience, mDNS hostname.
- The **Open Sight UI** button in the control panel.

Bookmark the first one. It's rock-solid because the Pi's IP is pinned.

---

## First-time hardware setup

You only do this once per Pi, when you first build it.

### What you need

- Orange Pi 5 (or 5B) — 4 GB RAM is plenty
- microSD card, 32 GB or larger (Class 10 / A2)
- USB-C 5 V / 3 A power supply (Pi 5 won't reliably boot at 2 A)
- USB webcam (any UVC camera that supports MJPEG — most do)
- Ethernet cable (Pi → robot radio's spare LAN port)
- microSD reader for your laptop

You don't need a monitor or keyboard for the Pi after first boot.
Setup is "headless" — flash the SD, plug it in, then drive it from
the laptop over SSH.

### Step 1 — flash the SD card

1. Download **Armbian** for Orange Pi 5 (Bookworm minimal):
   <https://www.armbian.com/orange-pi-5/>
2. Download **balenaEtcher**: <https://etcher.balena.io/>
3. Open Etcher → pick the Armbian `.img.xz` → pick the SD card → **Flash**.
4. Eject the card.

### Step 2 — first boot (one-time, with monitor)

For first boot you'll want a USB keyboard and HDMI monitor on the Pi
just for ~5 minutes:

1. Insert SD card. Plug in keyboard, monitor, USB camera, ethernet
   (to a regular network — your house, school, or the robot's radio).
   Plug in USB-C power.
2. Wait for the login prompt. First Armbian login is `root` / `1234`;
   it'll force you to change the password and create a regular user.
   **Use the username `orangepi`** — the rest of this guide assumes it.
3. Once logged in as `orangepi`, run:
   ```bash
   sudo systemctl enable --now ssh
   ip a
   ```
   Note the IP address. On the robot's radio it's whatever DHCP gave
   you at first; we'll pin it to `.11` during setup.
4. Unplug monitor + keyboard. The rest is from your laptop.

### Step 3 — find the Pi from your laptop

Your laptop should be on the same network as the Pi (same WiFi or
plugged into the radio).

```bash
ping orangepi.local
# or use the IP you noted from Step 2
```

If `orangepi.local` doesn't resolve, your network blocks mDNS — use
the IP. Either works for the rest of the setup.

### Step 4 — provision from the laptop

```bash
python start.py
```

Click **Set up Vision Pi**. The wizard will:

1. Ask for the Pi's host (`orangepi.local` or its IP) and user (`orangepi`).
2. rsync this whole `orangepi/` folder onto the Pi.
3. Run `install.sh` on the Pi, which:
   - apt-installs `ffmpeg`, `python3-venv`, `v4l-utils`
   - creates a Python venv and installs FastAPI / uvicorn / pyntcore
   - **pins the Pi's IP to `10.TE.AM.11`** on `eth0`
   - drops a sudoers rule so the rio can `systemctl restart` later
   - installs and starts the `cold-fusion-sight` systemd service
4. Set up SSH keys both directions (Pi ↔ admin@rio, Pi ↔ lvuser@rio).
5. Write `pi_target.json` at the repo root so the rio knows where the
   Pi lives once you deploy.

When done, click **Open Sight UI**. Your browser lands on
`http://10.TE.AM.11:8080/`. You should see CONNECTED in green and a
live camera feed.

### Step 5 — the very next deploy

Press **Deploy to Robot**. The rio gets the new code (including
`pi_target.json`); on its next boot, `orangepi_pusher` will SSH the
Pi and verify the orangepi/ files match. From then on, every Deploy
keeps both in sync automatically. **You never touch the Pi directly
again unless you want to.**

---

## Day-to-day use

- **Drive the robot:** control panel → **Connect** → DriverStation.
- **Push code:** **Deploy to Robot**. Sends rio code, and the rio
  passes any orangepi/ changes to the Pi on next boot.
- **Open the UI:** **Open Sight UI** (or bookmark `http://10.12.79.11:8080/`).
- **Aim & shoot:** click on the camera. rio rotates, dials in distance
  from LaserCAN, fires.
- **Force-push the Pi without rebooting the rio:** **Update Vision Pi**.
  Useful when iterating on HTML/CSS/JS — push from laptop, no rio reboot.

## Cross-host SSH

After provisioning, both directions are passwordless:

```bash
# Laptop:
ssh admin@10.12.79.2          # rio
ssh orangepi@10.12.79.11      # Pi

# From the Pi:
ssh admin@10.12.79.2          # rio (Pi's key trusted)

# From the rio (login first as admin):
ssh orangepi@10.12.79.11      # Pi (admin's key trusted)

# Robot code on the rio runs as `lvuser` and uses *its own* key, also
# trusted on the Pi — that's how `orangepi_pusher.py` works without
# anyone typing a password.
```

## Troubleshooting

| Symptom                                 | Try                                                                |
|-----------------------------------------|--------------------------------------------------------------------|
| Can't `ping 10.12.79.11`                | Check Pi power, eth cable, the radio is the DHCP server, NOT a switch |
| **Set up Vision Pi** "Permission denied"| Re-enter Pi password; or run `ssh-copy-id orangepi@<host>` once    |
| Web UI loads but says **DISCONNECTED**  | rio's down, or Pi can't reach `10.TE.AM.2`; ssh to Pi and ping it  |
| New code didn't reach the Pi            | Check `journalctl -u cold-fusion-sight` and `/tmp/robot-log` on rio for `[orangepi-pusher]` lines |
| Camera frame is black                   | `v4l2-ctl --list-devices` on the Pi; reseat USB                    |
| LaserCAN reads "NO READING"             | CAN ID matches `constants.CANIDs.LASERCAN` (default 36)?           |
| Pi UI laggy                             | Lower `CAMERA_FPS` in `sight.env` and `sudo systemctl restart cold-fusion-sight` |
| Pi works at home, fails on the robot    | Static IP needs `eth0`; if your Pi labels it `enP4p65s0` or similar, edit `/etc/NetworkManager/system-connections/cold-fusion-eth0.nmconnection` |

## When to re-run "Set up Vision Pi"

- You re-flashed the SD card.
- You changed team numbers (the static IP needs to change).
- You replaced the Pi with another one.
- The rio's lvuser key got deleted somehow (e.g. you wiped the rio).

Re-running is safe and idempotent — it just refreshes everything.

## What lives where

```
your repo/
├── orangepi/              ← Pi-side code (server.py, static/, install.sh)
├── orangepi_pusher.py     ← rio module: ships orangepi/ to the Pi at boot
├── pi_target.json         ← {"host": "10.12.79.11", ...} written by setup
├── setup_orangepi.py      ← one-time provisioning wizard
├── update_orangepi.py     ← force-push from laptop without rebooting rio
└── documentation/orangepi.md  ← (you are here)
```

On the Pi:

```
/home/orangepi/cold-fusion-sight/
├── server.py
├── static/
├── .venv/
├── sight.env              ← TEAM=1279, CAMERA_*, HTTP_PORT
└── .deploy_hash           ← what version of orangepi/ is currently installed
```

On the rio (after `robotpy deploy`):

```
/home/lvuser/py/
├── robot.py
├── orangepi/              ← ships every deploy; pusher reads from here
├── orangepi_pusher.py
└── pi_target.json
```
